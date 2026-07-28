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

"""Engine lifecycle: the tokio-to-asyncio bridge must work end to end."""

from __future__ import annotations

import asyncio

import pytest

from drasi import Drasi, DrasiError

from .helpers import wait_for_query_running, wait_for_rows


async def test_create_returns_an_awaitable_engine() -> None:
    drasi = await Drasi.create("t-create")
    try:
        assert drasi.id == "t-create"
        assert repr(drasi) == "Drasi(id='t-create')"
    finally:
        await drasi.close()


async def test_start_stop_toggles_is_running() -> None:
    drasi = await Drasi.create("t-lifecycle")
    try:
        assert await drasi.is_running() is False
        await drasi.start()
        assert await drasi.is_running() is True
        await drasi.stop()
        assert await drasi.is_running() is False
    finally:
        await drasi.close()


async def test_starting_an_already_running_engine_is_rejected() -> None:
    drasi = await Drasi.create("t-start-twice")
    try:
        await drasi.start()
        with pytest.raises(DrasiError) as caught:
            await drasi.start()
        assert caught.value.code == "ENGINE_FAILURE"
        assert "already running" in str(caught.value)
        assert await drasi.is_running() is True
    finally:
        await drasi.close()


async def test_an_engine_can_process_changes_after_stop_then_start() -> None:
    drasi = await Drasi.create("t-restart")
    try:
        await drasi.add_python_source("orders")
        await drasi.add_query("q", "MATCH (o:Order) RETURN o.id AS id", ["orders"])
        await drasi.start()
        await wait_for_query_running(drasi, "q")
        await drasi.stop()
        assert await drasi.is_running() is False

        await drasi.start()
        await wait_for_query_running(drasi, "q")
        await drasi.push_change(
            "orders",
            {"op": "insert", "id": "o1", "labels": ["Order"], "properties": {"id": "o1"}},
        )

        assert await wait_for_rows(drasi, "q") == [{"id": "o1"}]
    finally:
        await drasi.close()


async def test_a_query_added_before_start_runs_exactly_once() -> None:
    """Registering a query before `start()` must leave it running, not in error.

    `drasi-lib` 0.8.9 starts an auto-start query the moment it is added, with
    no `is_running()` guard (`add_source` and `add_reaction` both have one), so
    `start()` would start it a second time. That left the query reporting
    `Error` ("already running") while it was in fact running, and tripped an
    upstream `debug_assert!` as a hard panic whenever the first start had
    finished transitioning. The binding suppresses the premature start and
    starts the query itself, so both orderings behave the same.
    """
    drasi = await Drasi.create("t-add-then-start")
    try:
        await drasi.add_python_source("orders")
        await drasi.add_query("q", "MATCH (o:Order) RETURN o.id AS id", ["orders"])

        assert await drasi.get_query_status("q") == "Added"

        await drasi.start()
        await wait_for_query_running(drasi, "q")
        assert await drasi.get_query_status("q") == "Running"

        await drasi.push_change(
            "orders",
            {"op": "insert", "id": "o1", "labels": ["Order"], "properties": {"id": "o1"}},
        )
        assert await wait_for_rows(drasi, "q") == [{"id": "o1"}]
    finally:
        await drasi.close()


async def test_close_is_idempotent_but_start_after_close_is_rejected() -> None:
    drasi = await Drasi.create("t-close-twice")
    await drasi.start()

    await drasi.close()
    await drasi.close()

    assert await drasi.is_running() is False
    with pytest.raises(DrasiError) as caught:
        await drasi.start()
    assert caught.value.code == "ENGINE_FAILURE"
    assert "shut down" in str(caught.value)


async def test_async_context_manager_closes_the_engine() -> None:
    async with await Drasi.create("t-ctx") as drasi:
        await drasi.start()
        assert await drasi.is_running() is True


async def test_concurrent_engines_do_not_block_each_other() -> None:
    engines = await asyncio.gather(*(Drasi.create(f"t-par-{i}") for i in range(4)))
    try:
        await asyncio.gather(*(engine.start() for engine in engines))
        running = await asyncio.gather(*(engine.is_running() for engine in engines))
        assert running == [True] * 4
    finally:
        await asyncio.gather(*(engine.close() for engine in engines))


async def test_engine_work_does_not_starve_the_event_loop() -> None:
    """A pending Rust future must not hold the GIL and block other coroutines."""
    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        for _ in range(20):
            ticks += 1
            await asyncio.sleep(0.005)

    async with await Drasi.create("t-loop") as drasi:
        await asyncio.gather(ticker(), drasi.start())

    assert ticks == 20


def test_create_outside_a_running_loop_is_a_clear_error() -> None:
    with pytest.raises(RuntimeError, match="no running event loop"):
        Drasi.create("t-no-loop")


async def test_module_and_engine_host_info_agree() -> None:
    """One documented shape, so callers can check compatibility before creating an engine."""
    from drasi import host_info

    async with await Drasi.create("t-host-info") as drasi:
        assert drasi.host_info() == host_info()

    info = host_info()
    assert info["target_triple"]
    assert info["arch_suffix"]
    assert info["ffi_sdk_version"]


async def test_a_closed_engine_refuses_further_changes() -> None:
    """Adding to a closed engine used to succeed, and then never run.

    The component was accepted, no error was raised, and the only symptom was
    that nothing happened — discovered much later, if at all.
    """
    drasi = await Drasi.create("t-closed")
    await drasi.start()
    await drasi.close()

    for attempt in (
        lambda: drasi.add_python_source("s"),
        lambda: drasi.add_query("q", "MATCH (o:Order) RETURN o.id AS id", ["s"]),
        lambda: drasi.push_change("s", {"op": "insert", "id": "o1"}),
        lambda: drasi.load_plugins("./plugins"),
    ):
        with pytest.raises(DrasiError) as caught:
            await attempt()
        assert caught.value.code == "ENGINE_CLOSED"


async def test_a_closed_engine_can_still_be_inspected() -> None:
    """Reading is harmless, and useful when working out what happened."""
    drasi = await Drasi.create("t-closed-reads")
    await drasi.start()
    await drasi.add_python_source("s")
    await drasi.close()

    assert await drasi.is_running() is False
    assert any(source_id == "s" for source_id, _ in await drasi.list_sources())
    assert drasi.host_info()["target_triple"]


async def test_leaving_the_context_manager_closes_for_good() -> None:
    async with await Drasi.create("t-ctx-closed") as drasi:
        await drasi.start()

    with pytest.raises(DrasiError) as caught:
        await drasi.add_python_source("s")
    assert caught.value.code == "ENGINE_CLOSED"
