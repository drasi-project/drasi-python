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

from drasi import Drasi


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
