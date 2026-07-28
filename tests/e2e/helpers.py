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

"""Helpers for end-to-end tests.

Continuous queries are asynchronous by nature, so tests poll for an expected
state rather than sleeping for a fixed duration. Every helper has a deadline so
a regression fails fast instead of hanging the suite.
"""

from __future__ import annotations

import asyncio
from typing import Any

from drasi import Drasi

DEFAULT_TIMEOUT = 10.0
POLL_INTERVAL = 0.01


async def wait_for(
    predicate: Any,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    description: str = "condition",
) -> None:
    """Waits until `predicate()` returns true."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(POLL_INTERVAL)
    raise AssertionError(f"timed out after {timeout}s waiting for {description}")


async def wait_for_query_running(
    engine: Drasi,
    query_id: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> None:
    """Waits until a query reports `Running`.

    `add_query` provisions a query and returns; auto-start then happens in the
    background. Reading results before that completes raises "is not running",
    so tests wait for the transition rather than racing it.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    statuses: list[tuple[str, str]] = []
    while loop.time() < deadline:
        statuses = await engine.list_queries()
        if any(entry == query_id and status == "Running" for entry, status in statuses):
            return
        await asyncio.sleep(POLL_INTERVAL)
    raise AssertionError(
        f"timed out after {timeout}s waiting for query {query_id!r} to run; last saw {statuses!r}"
    )


async def wait_for_rows(
    engine: Drasi,
    query_id: str,
    *,
    count: int = 1,
    timeout: float = DEFAULT_TIMEOUT,
) -> list[dict[str, Any]]:
    """Waits until a query's result set has exactly `count` rows, then returns it.

    Waiting for an exact count rather than "at least one" keeps assertions
    meaningful when a change is expected to remove rows.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    rows: list[dict[str, Any]] = []
    while loop.time() < deadline:
        rows = await engine.get_query_results(query_id)
        if len(rows) == count:
            return rows
        await asyncio.sleep(POLL_INTERVAL)
    raise AssertionError(
        f"timed out after {timeout}s waiting for {count} row(s) from "
        f"query {query_id!r}; last saw {rows!r}"
    )


async def wait_for_at_least_rows(
    engine: Drasi,
    query_id: str,
    *,
    count: int = 1,
    timeout: float = DEFAULT_TIMEOUT,
) -> list[dict[str, Any]]:
    """Waits until a query's result set has at least `count` rows.

    Use this, not `wait_for_rows`, for a source that keeps producing. A counter
    source emitting every few milliseconds can step straight past an exact
    count between two polls, so waiting for equality there is a race that fails
    once the runner is loaded enough.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    rows: list[dict[str, Any]] = []
    while loop.time() < deadline:
        rows = await engine.get_query_results(query_id)
        if len(rows) >= count:
            return rows
        await asyncio.sleep(POLL_INTERVAL)
    raise AssertionError(
        f"timed out after {timeout}s waiting for at least {count} row(s) from "
        f"query {query_id!r}; last saw {len(rows)}"
    )


async def wait_for_result(
    engine: Drasi,
    query_id: str,
    expected: list[dict[str, Any]],
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> None:
    """Waits until a query's result set equals `expected`.

    Use this rather than `wait_for_rows` when a change alters a row in place:
    the row count does not change, so waiting on the count alone would race.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    rows: list[dict[str, Any]] = []
    while loop.time() < deadline:
        rows = await engine.get_query_results(query_id)
        if rows == expected:
            return
        await asyncio.sleep(POLL_INTERVAL)
    raise AssertionError(
        f"timed out after {timeout}s waiting for query {query_id!r} to equal "
        f"{expected!r}; last saw {rows!r}"
    )


class EventRecorder:
    """Collects the diffs delivered to a Python reaction."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.diffs: list[dict[str, Any]] = []
        self._cursor = 0

    def __call__(self, event: dict[str, Any]) -> None:
        self.events.append(event)
        self.diffs.extend(event["results"])

    async def take(self, count: int, *, timeout: float = DEFAULT_TIMEOUT) -> list[dict[str, Any]]:
        """Waits for the next `count` unread diffs and returns them."""
        await wait_for(
            lambda: len(self.diffs) - self._cursor >= count,
            timeout=timeout,
            description=f"{count} more diff(s); saw {self.diffs[self._cursor :]!r}",
        )
        taken = self.diffs[self._cursor : self._cursor + count]
        self._cursor += count
        return taken


async def collect_events(engine: Drasi, reaction_id: str, query_ids: list[str]) -> EventRecorder:
    """Registers a recording reaction over the given queries."""
    recorder = EventRecorder()
    await engine.add_python_reaction(reaction_id, query_ids, recorder)
    return recorder
