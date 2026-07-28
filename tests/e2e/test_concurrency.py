# Copyright 2026 The Drasi Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Concurrency paths where PyO3 releases the GIL around engine work."""

from __future__ import annotations

import asyncio
from typing import Any

from drasi import Drasi, Stream
from drasi.types import QueryResultEvent, SourceChange

from .helpers import wait_for, wait_for_query_running, wait_for_rows

OPEN_ORDERS = "MATCH (o:Order) WHERE o.status = 'open' RETURN o.id AS id, o.total AS total"


def order(order_id: str, *, status: str = "open", total: int = 0) -> SourceChange:
    return {
        "op": "insert",
        "id": order_id,
        "labels": ["Order"],
        "properties": {"id": order_id, "status": status, "total": total},
    }


async def take(stream: Stream, count: int, *, timeout: float = 10.0) -> list[dict[str, Any]]:
    async def collect() -> list[Any]:
        items: list[Any] = []
        async for item in stream:
            items.append(item)
            if len(items) >= count:
                return items
        return items

    return await asyncio.wait_for(collect(), timeout)


async def running_orders_engine(engine: Drasi) -> Drasi:
    await engine.add_python_source("orders")
    await engine.add_query("open", OPEN_ORDERS, ["orders"])
    await engine.start()
    await wait_for_query_running(engine, "open")
    return engine


async def test_concurrent_pushes_are_all_applied_once(engine: Drasi) -> None:
    drasi = await running_orders_engine(engine)

    await asyncio.gather(*(drasi.push_change("orders", order(f"o{i}", total=i)) for i in range(20)))

    rows = await wait_for_rows(drasi, "open", count=20)
    assert sorted(rows, key=lambda row: row["total"]) == [
        {"id": f"o{i}", "total": i} for i in range(20)
    ]


async def test_concurrent_queries_over_one_source_keep_independent_results(engine: Drasi) -> None:
    await engine.add_python_source("orders")
    await engine.add_query(
        "open", "MATCH (o:Order) WHERE o.status = 'open' RETURN o.id AS id", ["orders"]
    )
    await engine.add_query(
        "large", "MATCH (o:Order) WHERE o.total >= 100 RETURN o.id AS id", ["orders"]
    )
    await engine.start()
    await asyncio.gather(
        wait_for_query_running(engine, "open"),
        wait_for_query_running(engine, "large"),
    )

    await asyncio.gather(
        engine.push_change("orders", order("open-small", total=1)),
        engine.push_change("orders", order("closed-large", status="closed", total=100)),
        engine.push_change("orders", order("open-large", total=200)),
    )

    open_rows, large_rows = await asyncio.gather(
        wait_for_rows(engine, "open", count=2),
        wait_for_rows(engine, "large", count=2),
    )
    assert sorted(open_rows, key=lambda row: row["id"]) == [
        {"id": "open-large"},
        {"id": "open-small"},
    ]
    assert sorted(large_rows, key=lambda row: row["id"]) == [
        {"id": "closed-large"},
        {"id": "open-large"},
    ]


async def test_simultaneous_streams_on_one_query_each_receive_the_event(engine: Drasi) -> None:
    drasi = await running_orders_engine(engine)
    streams = await asyncio.gather(*(drasi.query_results("open") for _ in range(3)))
    readers = [asyncio.create_task(take(stream, 1)) for stream in streams]

    await drasi.push_change("orders", order("o1", total=42))

    events = await asyncio.gather(*readers)
    assert [batch[0]["results"][0]["data"] for batch in events] == [
        {"id": "o1", "total": 42},
        {"id": "o1", "total": 42},
        {"id": "o1", "total": 42},
    ]


async def test_a_slow_durable_reaction_does_not_block_query_updates(
    tmp_path: Any,
) -> None:
    drasi = await Drasi.create(
        "t-slow-reaction", state_store={"kind": "redb", "path": str(tmp_path / "state.redb")}
    )
    try:
        await running_orders_engine(drasi)
        started = asyncio.Event()
        release = asyncio.Event()
        seen: list[str] = []

        async def handler(event: QueryResultEvent) -> None:
            started.set()
            await release.wait()
            seen.extend(diff["data"]["id"] for diff in event["results"])

        await drasi.add_durable_python_reaction("slow", ["open"], handler)
        await drasi.push_change("orders", order("o1", total=1))
        await asyncio.wait_for(started.wait(), timeout=10)

        await asyncio.gather(
            drasi.push_change("orders", order("o2", total=2)),
            drasi.push_change("orders", order("o3", total=3)),
        )

        rows = await wait_for_rows(drasi, "open", count=3)
        assert sorted(rows, key=lambda row: row["id"]) == [
            {"id": "o1", "total": 1},
            {"id": "o2", "total": 2},
            {"id": "o3", "total": 3},
        ]
        assert seen == []

        release.set()
        await wait_for(lambda: sorted(seen) == ["o1", "o2", "o3"], description="slow reaction")
    finally:
        await drasi.close()
