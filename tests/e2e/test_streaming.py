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

"""Observing an engine as it runs.

Three distinct things stream, and conflating them is easy: lifecycle *events*,
component *logs*, and query *results*.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from drasi import Drasi, DrasiError, Stream

from .helpers import wait_for, wait_for_query_running

OPEN_ORDERS = "MATCH (o:Order) WHERE o.status = 'open' RETURN o.id AS id"


def order(order_id: str, status: str = "open") -> dict[str, Any]:
    return {
        "op": "insert",
        "id": order_id,
        "labels": ["Order"],
        "properties": {"id": order_id, "status": status},
    }


async def running_engine(engine: Drasi) -> Drasi:
    await engine.start()
    await engine.add_python_source("orders")
    await engine.add_query("open", OPEN_ORDERS, ["orders"])
    await wait_for_query_running(engine, "open")
    return engine


async def take(stream: Stream, count: int, *, timeout: float = 10.0) -> list[dict[str, Any]]:
    """Reads `count` items, failing rather than hanging if they never arrive."""

    async def collect() -> list[dict[str, Any]]:
        items = []
        async for item in stream:
            items.append(item)
            if len(items) >= count:
                return items
        return items

    return await asyncio.wait_for(collect(), timeout)


# --------------------------------------------------------------------- results


async def test_query_results_stream_as_an_async_iterator(engine: Drasi) -> None:
    drasi = await running_engine(engine)
    results = await drasi.query_results("open")

    await drasi.push_change("orders", order("o1"))
    [event] = await take(results, 1)

    assert event["query_id"] == "open"
    assert event["results"][0]["type"] == "ADD"
    assert event["results"][0]["data"] == {"id": "o1"}


async def test_result_stream_sees_updates_and_deletes(engine: Drasi) -> None:
    drasi = await running_engine(engine)
    results = await drasi.query_results("open")

    await drasi.push_change("orders", order("o1"))
    await drasi.push_change("orders", {**order("o1"), "op": "update"})
    # Closing the order takes it out of the result set.
    await drasi.push_change("orders", {**order("o1", status="closed"), "op": "update"})

    kinds = [diff["type"] for event in await take(results, 2) for diff in event["results"]]
    assert kinds[0] == "ADD"
    assert "DELETE" in kinds


async def test_two_result_streams_are_independent(engine: Drasi) -> None:
    drasi = await running_engine(engine)
    first = await drasi.query_results("open")
    second = await drasi.query_results("open")

    await drasi.push_change("orders", order("o1"))

    assert (await take(first, 1))[0]["results"][0]["data"] == {"id": "o1"}
    assert (await take(second, 1))[0]["results"][0]["data"] == {"id": "o1"}


async def test_result_callback_receives_the_same_events(engine: Drasi) -> None:
    drasi = await running_engine(engine)
    seen: list[dict[str, Any]] = []
    await drasi.on_query_results("open", seen.append)

    await drasi.push_change("orders", order("o1"))
    await wait_for(lambda: len(seen) >= 1, description="a result callback")

    assert seen[0]["results"][0]["data"] == {"id": "o1"}


# ---------------------------------------------------------------------- events


async def test_query_events_replay_history(engine: Drasi) -> None:
    """A subscriber that arrives late still learns how the query got here."""
    drasi = await running_engine(engine)
    events = await drasi.query_events("open")

    [first] = await take(events, 1)
    assert first["component_id"] == "open"
    assert "status" in first


async def test_source_and_reaction_events_stream(engine: Drasi) -> None:
    drasi = await running_engine(engine)
    await drasi.add_python_reaction("noop", ["open"], lambda _: None)

    source_events = await drasi.source_events("orders")
    reaction_events = await drasi.reaction_events("noop")

    assert (await take(source_events, 1))[0]["component_id"] == "orders"
    assert (await take(reaction_events, 1))[0]["component_id"] == "noop"


async def test_all_events_covers_every_component(engine: Drasi) -> None:
    drasi = await running_engine(engine)
    events = await drasi.all_events()

    await drasi.add_python_source("later")
    seen = await take(events, 1, timeout=15.0)
    assert "component_id" in seen[0]


async def test_event_callbacks_fire(engine: Drasi) -> None:
    drasi = await running_engine(engine)
    seen: list[dict[str, Any]] = []
    await drasi.on_query_events("open", seen.append)

    await wait_for(lambda: len(seen) >= 1, description="an event callback")
    assert seen[0]["component_id"] == "open"


async def test_all_source_and_reaction_event_callbacks_fire(engine: Drasi) -> None:
    drasi = await running_engine(engine)
    all_seen: list[dict[str, Any]] = []
    source_seen: list[dict[str, Any]] = []
    reaction_seen: list[dict[str, Any]] = []

    await drasi.on_all_events(all_seen.append)
    await drasi.on_source_events("orders", source_seen.append)
    await drasi.add_python_reaction("noop", ["open"], lambda _: None)
    await drasi.on_reaction_events("noop", reaction_seen.append)

    await wait_for(lambda: any(event["component_id"] == "orders" for event in source_seen))
    await wait_for(lambda: any(event["component_id"] == "noop" for event in reaction_seen))
    assert any("component_id" in event for event in all_seen)


# ------------------------------------------------------------------------ logs


async def test_log_streams_are_available_for_each_component(engine: Drasi) -> None:
    drasi = await running_engine(engine)
    await drasi.add_python_reaction("noop", ["open"], lambda _: None)

    # Opening them must succeed even when nothing has logged yet.
    for stream in (
        await drasi.query_logs("open"),
        await drasi.source_logs("orders"),
        await drasi.reaction_logs("noop"),
    ):
        assert isinstance(stream, Stream)


async def test_log_callbacks_are_accepted(engine: Drasi) -> None:
    drasi = await running_engine(engine)
    await drasi.add_python_reaction("noop", ["open"], lambda _: None)
    await drasi.on_query_logs("open", lambda _: None)
    await drasi.on_source_logs("orders", lambda _: None)
    await drasi.on_reaction_logs("noop", lambda _: None)


# ---------------------------------------------------------------------- errors


async def test_streaming_an_unknown_component_is_rejected(engine: Drasi) -> None:
    await engine.start()
    with pytest.raises(DrasiError):
        await engine.query_events("does-not-exist")


@pytest.mark.parametrize("method", ["on_query_events", "on_query_logs", "on_query_results"])
async def test_callbacks_must_be_callable(engine: Drasi, method: str) -> None:
    drasi = await running_engine(engine)
    with pytest.raises(DrasiError) as caught:
        await getattr(drasi, method)("open", "not callable")
    assert caught.value.code == "CONFIG_INVALID"


async def test_a_stream_ends_when_the_engine_closes() -> None:
    """An open iterator must terminate on shutdown rather than hang."""
    drasi = await Drasi.create("t-stream-close")
    await running_engine(drasi)
    results = await drasi.query_results("open")

    await drasi.close()

    async def drain() -> list[Any]:
        return [item async for item in results]

    assert await asyncio.wait_for(drain(), timeout=10.0) == []


async def test_stream_has_a_useful_repr(engine: Drasi) -> None:
    drasi = await running_engine(engine)
    assert "open" in repr(await drasi.query_results("open"))
