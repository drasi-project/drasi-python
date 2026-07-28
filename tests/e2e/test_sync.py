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

"""The blocking facade.

These run outside an event loop, so they are plain `def` tests rather than
`async def` ones.
"""

from __future__ import annotations

import inspect

import pytest

import drasi
from drasi.sync import Drasi as SyncDrasi
from drasi.sync import Stream as SyncStream
from drasi.types import QueryResultEvent, SourceChange

OPEN_ORDERS = "MATCH (o:Order) WHERE o.status = 'open' RETURN o.id AS id"


def order(order_id: str, status: str = "open") -> SourceChange:
    return {
        "op": "insert",
        "id": order_id,
        "labels": ["Order"],
        "properties": {"id": order_id, "status": status},
    }


def running() -> SyncDrasi:
    engine = SyncDrasi.create("sync-test")
    engine.start()
    engine.add_python_source("orders")
    engine.add_query("open", OPEN_ORDERS, ["orders"])
    engine.wait_for_query("open")
    return engine


def test_a_full_cycle_works_without_await() -> None:
    with running() as engine:
        engine.push_change("orders", order("o1"))
        engine.push_change("orders", order("o2"))

        # No polling helper here: the point is that these calls block.
        engine.wait_for_query("open")
        rows = engine.get_query_results("open")
        while len(rows) < 2:
            rows = engine.get_query_results("open")

        assert sorted(row["id"] for row in rows) == ["o1", "o2"]


def test_the_context_manager_closes_the_engine() -> None:
    with running() as engine:
        assert engine.is_running() is True
    assert engine.is_running() is False


def test_streams_are_ordinary_iterators() -> None:
    with running() as engine:
        results = engine.query_results("open")
        assert isinstance(results, SyncStream)

        engine.push_change("orders", order("o1"))

        seen: list[str] = []
        for event in results:
            seen.extend(diff["data"]["id"] for diff in event["results"])
            break

        assert seen == ["o1"]


def test_a_stream_stops_when_the_engine_closes() -> None:
    engine = running()
    results = engine.query_results("open")
    engine.close()

    # StopAsyncIteration must surface as StopIteration, so `for` terminates.
    assert list(results) == []


def test_callbacks_work_too() -> None:
    with running() as engine:
        seen: list[QueryResultEvent] = []
        engine.on_query_results("open", seen.append)
        engine.push_change("orders", order("o1"))

        while not seen:
            engine.get_query_results("open")

        assert seen[0]["results"][0]["data"] == {"id": "o1"}


def test_errors_are_the_same_typed_exceptions() -> None:
    with running() as engine:
        with pytest.raises(drasi.SourceError) as caught:
            engine.push_change("orders", {"id": "missing-op"})
        assert caught.value.code == "CHANGE_OP_REQUIRED"


def test_introspection_is_available() -> None:
    with running() as engine:
        assert engine.get_query_status("open") == "Running"
        assert engine.get_source_status("orders") == "Running"
        assert "live_results_count" in engine.get_query_metrics("open")
        assert "sources_without_schema" in engine.get_graph_schema()
        assert engine.host_info()["target_triple"]


def test_from_config_builds_a_started_engine() -> None:
    with SyncDrasi.from_config({"id": "sync-declared"}) as engine:
        assert engine.id == "sync-declared"
        assert engine.is_running() is True


def test_repr_identifies_the_engine() -> None:
    with running() as engine:
        assert "sync.Drasi(id='sync-test')" == repr(engine)


async def test_using_it_inside_a_running_loop_is_refused() -> None:
    """Blocking a running loop would deadlock, so it is refused explicitly."""
    with pytest.raises(RuntimeError, match="use drasi.Drasi"):
        SyncDrasi.create("nope")


def test_the_facade_covers_the_async_api() -> None:
    """Anything on the async engine should be reachable from the sync one."""
    asynchronous = {name for name in dir(drasi.Drasi) if not name.startswith("_")}
    synchronous = {name for name in dir(SyncDrasi) if not name.startswith("_")}

    missing = asynchronous - synchronous
    assert not missing, f"the sync facade is missing {sorted(missing)}"


def test_sync_methods_are_not_coroutines() -> None:
    """A method that returned a coroutine would defeat the purpose."""
    for name in dir(SyncDrasi):
        if name.startswith("_"):
            continue
        attribute = inspect.getattr_static(SyncDrasi, name)
        assert not inspect.iscoroutinefunction(attribute), name
