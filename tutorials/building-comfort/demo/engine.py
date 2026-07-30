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

"""The embedded Drasi engine that powers the Streamlit UI.

Streamlit re-runs its script top to bottom on every interaction, which is a poor
fit for a long-lived async engine. So the Drasi engine runs on its own asyncio
event loop in a background daemon thread, created exactly once (Streamlit caches
it with ``@st.cache_resource``). The engine:

1. installs the ``source/postgres`` and ``bootstrap/postgres`` plugins,
2. adds the Postgres source and the six continuous queries, and
3. registers a single **Python reaction** over all six queries.

The reaction keeps a thread-safe snapshot of every query's result set. Streamlit
reads that snapshot each run and renders it; there is no dashboard or SSE
reaction, and no bespoke web server -- the reaction *is* the application.

The UI's controls (set a room, reset, simulate) write plain SQL ``UPDATE``s to
Postgres via ``psycopg``. Drasi observes those writes through logical
replication and re-runs the affected queries, which calls the reaction, which
updates the snapshot -- the same path a real building-management app would take.
"""

from __future__ import annotations

import os

# Quiet the engine's default INFO logging so it doesn't swamp Streamlit's
# console. Set RUST_LOG=info (or debug) to watch what the engine is doing. This
# must happen before ``drasi`` is imported.
os.environ.setdefault("RUST_LOG", "warn")

import asyncio  # noqa: E402
import random  # noqa: E402
import threading  # noqa: E402
from typing import Any  # noqa: E402

import psycopg  # noqa: E402

from drasi import Drasi  # noqa: E402
from drasi.types import QueryResultEvent  # noqa: E402

from .config import (  # noqa: E402
    BOOTSTRAP_CONFIG,
    COMFORT_DEFAULTS,
    PSYCOPG_CONNECTION,
    SIMULATION_INTERVAL_S,
    SOURCE_CONFIG,
)
from .queries import ALL_QUERY_IDS, KEY_FIELDS, QUERIES  # noqa: E402

# Ranges chosen to straddle the comfortable band, so simulation makes alerts
# come and go rather than sitting at one extreme.
_SIM_TEMPERATURE = (55, 85)
_SIM_HUMIDITY = (20, 55)
_SIM_CO2 = (5, 904)


def _update_rooms(sql: str, params: tuple[Any, ...] = ()) -> None:
    """Run one UPDATE against the Room table on a short-lived connection."""
    with psycopg.connect(**PSYCOPG_CONNECTION) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)


class ComfortEngine:
    """Runs Drasi on a background loop and exposes a thread-safe snapshot."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Per query: a dict keyed by that query's primary-key field. The reaction
        # applies diffs into it; the UI reads a snapshot of the values.
        self._results: dict[str, dict[Any, dict[str, Any]]] = {}
        self._version = 0
        self._simulation = False

        self._loop: asyncio.AbstractEventLoop | None = None
        self._drasi: Drasi | None = None
        self._sim_task: asyncio.Task[None] | None = None
        self._room_ids: list[str] = []

        self._ready = threading.Event()
        self._error: BaseException | None = None

        self._thread = threading.Thread(target=self._run, name="drasi-comfort-engine", daemon=True)
        self._thread.start()

    # -- lifecycle (background thread) ---------------------------------------

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._start())
        except BaseException as exc:  # noqa: BLE001 - surfaced to the UI thread
            self._error = exc
            self._ready.set()
            return
        self._ready.set()
        loop.run_forever()

    async def _start(self) -> None:
        self._drasi = await Drasi.create("building-comfort")

        for plugin in ("source/postgres", "bootstrap/postgres"):
            await self._drasi.install_plugin(plugin)
        await self._drasi.start()

        await self._drasi.add_source("postgres", "db", SOURCE_CONFIG, bootstrap=BOOTSTRAP_CONFIG)

        for query_id, cypher, joins in QUERIES:
            await self._drasi.add_query(query_id, cypher, ["db"], joins=joins or None)
        for query_id, _, _ in QUERIES:
            await self._drasi.wait_for_query(query_id)

        # Prime the snapshot from the bootstrapped result sets, then let the
        # reaction keep it current.
        for query_id, _, _ in QUERIES:
            rows = await self._drasi.get_query_results(query_id)
            key_field = KEY_FIELDS[query_id]
            with self._lock:
                self._results[query_id] = {row[key_field]: row for row in rows}
        self._room_ids = await self._load_room_ids()

        await self._drasi.add_python_reaction("ui", ALL_QUERY_IDS, self._on_results)

    def _on_results(self, event: QueryResultEvent) -> None:
        """Apply a batch of diffs to the snapshot.

        ``add_python_reaction`` calls this synchronously. Every diff carries the
        affected row in ``data`` (for an UPDATE it equals ``after``), so the
        snapshot is maintained by row identity: upsert on ADD/UPDATE, drop on
        DELETE. Result sets are tiny, so this stays cheap.
        """
        query_id = event["query_id"]
        key_field = KEY_FIELDS[query_id]
        with self._lock:
            store = self._results.setdefault(query_id, {})
            for diff in event["results"]:
                row = diff.get("data") or diff.get("after")
                if row is None:
                    continue
                key = row.get(key_field)
                if diff["type"] == "DELETE":
                    store.pop(key, None)
                else:
                    store[key] = row
            self._version += 1

    async def _load_room_ids(self) -> list[str]:
        def _query() -> list[str]:
            with psycopg.connect(**PSYCOPG_CONNECTION) as conn:
                with conn.cursor() as cur:
                    cur.execute('SELECT id FROM "Room" ORDER BY id')
                    return [row[0] for row in cur.fetchall()]

        return await asyncio.get_event_loop().run_in_executor(None, _query)

    # -- readiness -----------------------------------------------------------

    def wait_ready(self, timeout: float = 180.0) -> None:
        """Block until the engine is running, raising if it failed to start."""
        if not self._ready.wait(timeout):
            raise TimeoutError("the Drasi engine did not start in time")
        if self._error is not None:
            raise RuntimeError(f"the Drasi engine failed to start: {self._error}")

    # -- reads (any thread) --------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Return the current result set of every query, plus engine flags."""
        with self._lock:
            results = {qid: list(store.values()) for qid, store in self._results.items()}
            return {
                "version": self._version,
                "simulation": self._simulation,
                "results": results,
                "error": str(self._error) if self._error else None,
            }

    # -- writes (any thread -> Postgres, observed via CDC) -------------------

    def set_room(self, room_id: str, temperature: int, humidity: int, co2: int) -> None:
        _update_rooms(
            'UPDATE "Room" SET temperature = %s, humidity = %s, co2 = %s WHERE id = %s',
            (temperature, humidity, co2, room_id),
        )

    def reset_room(self, room_id: str | None = None) -> None:
        """Reset one room, or every room when ``room_id`` is None."""
        d = COMFORT_DEFAULTS
        if room_id is None:
            _update_rooms(
                'UPDATE "Room" SET temperature = %s, humidity = %s, co2 = %s',
                (d["temperature"], d["humidity"], d["co2"]),
            )
        else:
            self.set_room(room_id, d["temperature"], d["humidity"], d["co2"])

    def set_simulation(self, enabled: bool) -> None:
        """Turn hands-free simulation on or off."""
        if self._loop is None:
            return
        future = asyncio.run_coroutine_threadsafe(self._set_simulation(enabled), self._loop)
        future.result(timeout=10)

    async def _set_simulation(self, enabled: bool) -> None:
        if enabled and self._sim_task is None:
            if not self._room_ids:
                self._room_ids = await self._load_room_ids()
            self._sim_task = asyncio.ensure_future(self._simulate())
            self._simulation = True
        elif not enabled and self._sim_task is not None:
            self._sim_task.cancel()
            self._sim_task = None
            self._simulation = False

    async def _simulate(self) -> None:
        loop = asyncio.get_event_loop()
        try:
            while True:
                room = random.choice(self._room_ids)
                temperature = random.randint(*_SIM_TEMPERATURE)
                humidity = random.randint(*_SIM_HUMIDITY)
                co2 = random.randint(*_SIM_CO2)
                # Run the blocking write off the event loop so the reaction keeps
                # delivering while simulation is on.
                await loop.run_in_executor(None, self.set_room, room, temperature, humidity, co2)
                await asyncio.sleep(SIMULATION_INTERVAL_S)
        except asyncio.CancelledError:
            pass
