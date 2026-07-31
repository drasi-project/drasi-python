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

This one file holds everything behind the demo: the configuration, the six
continuous queries, and the engine that runs them.

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
from dataclasses import dataclass, field  # noqa: E402
from typing import Any  # noqa: E402

import psycopg  # noqa: E402

from drasi import Drasi  # noqa: E402
from drasi.types import QueryResultEvent  # noqa: E402

# =============================================================================
# Configuration -- everything read from the environment with defaults.
# =============================================================================

POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.environ.get("POSTGRES_PORT", "5732"))
POSTGRES_DATABASE = os.environ.get("POSTGRES_DATABASE", "building_comfort")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "drasi_user")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "drasi_password")
POSTGRES_SSLMODE = os.environ.get("POSTGRES_SSLMODE", "prefer")

# The Drasi source plugin spells the connection keys the same way the Node.js
# binding does (camelCase); Drasi passes plugin config through untouched.
SOURCE_CONNECTION = {
    "host": POSTGRES_HOST,
    "port": POSTGRES_PORT,
    "database": POSTGRES_DATABASE,
    "user": POSTGRES_USER,
    "password": POSTGRES_PASSWORD,
    "sslMode": POSTGRES_SSLMODE,
}

# psycopg spells the database key ``dbname`` rather than ``database``. The demo
# writes room updates directly to Postgres through this connection so Drasi
# observes them via CDC -- exactly as a real building-management app would.
PSYCOPG_CONNECTION = {
    "host": POSTGRES_HOST,
    "port": POSTGRES_PORT,
    "dbname": POSTGRES_DATABASE,
    "user": POSTGRES_USER,
    "password": POSTGRES_PASSWORD,
}

# The Postgres source replicates these three tables. They are schema-qualified
# here (``public.Room``) while ``tableKeys`` uses the bare table name; the node
# label Drasi sees is the bare name, so the Cypher matches (r:Room) etc.
SOURCE_CONFIG = {
    **SOURCE_CONNECTION,
    "tables": ["public.Building", "public.Floor", "public.Room"],
    "tableKeys": [
        {"table": "Building", "keyColumns": ["id"]},
        {"table": "Floor", "keyColumns": ["id"]},
        {"table": "Room", "keyColumns": ["id"]},
    ],
    "slotName": "drasi_building_comfort_slot",
    "publicationName": "drasi_building_comfort_pub",
}

# The bootstrap provider loads the rows that already exist when the query starts,
# so the dashboard is populated before any change arrives.
BOOTSTRAP_CONFIG = {"kind": "postgres", **SOURCE_CONNECTION}

# Comfortable defaults. floor(50 + (70-72) + (40-42) + 0) = 46, inside 40-50.
COMFORT_DEFAULTS = {"temperature": 70, "humidity": 40, "co2": 10}

# The comfortable band. A room, floor or building outside it raises an alert.
COMFORT_MIN = 40
COMFORT_MAX = 50

# How often simulation mode assigns a random room new readings, in seconds.
SIMULATION_INTERVAL_S = float(os.environ.get("SIMULATION_INTERVAL_S", "3"))

# =============================================================================
# The six continuous queries.
# =============================================================================
#
# Each query is written out in full so you can read (or copy) exactly what Drasi
# runs. They all compute the same comfort level:
#
#     floor(50 + (temperature - 72) + (humidity - 42)
#           + CASE WHEN co2 > 500 THEN (co2 - 500) / 25 ELSE 0 END)
#
# A value between 40 and 50 is comfortable; the seed values (70F, 40%, 10 ppm)
# give floor(50 + (70-72) + (40-42) + 0) = 46.
#
# The Room -> Floor -> Building hierarchy is walked through two *synthetic
# joins*. Drasi does not read Postgres foreign keys, so each query declares the
# relationships it needs -- Room.floor_id -> Floor.id, and Floor.building_id ->
# Building.id -- as a plain mapping passed to ``add_query``.

PART_OF_FLOOR = {
    "id": "PART_OF_FLOOR",
    "keys": [
        {"label": "Room", "property": "floor_id"},
        {"label": "Floor", "property": "id"},
    ],
}

PART_OF_BUILDING = {
    "id": "PART_OF_BUILDING",
    "keys": [
        {"label": "Floor", "property": "building_id"},
        {"label": "Building", "property": "id"},
    ],
}

# Query ids -- the UI reads each query's result set from the snapshot by these.
BUILDING_COMFORT_UI = "building-comfort-ui"
BUILDING_COMFORT_LEVEL = "building-comfort-level-calc"
FLOOR_COMFORT_LEVEL = "floor-comfort-level-calc"
ROOM_ALERT = "room-alert"
FLOOR_ALERT = "floor-alert"
BUILDING_ALERT = "building-alert"


@dataclass(frozen=True)
class Query:
    """One continuous query: how to register it and how to index its rows."""

    id: str
    key: str  # the RETURN column that identifies each row (its primary key)
    cypher: str
    joins: list[dict[str, Any]] = field(default_factory=list)


QUERIES = [
    # One row per room, with its comfort level. Drives the building view.
    Query(
        id=BUILDING_COMFORT_UI,
        key="RoomId",
        joins=[PART_OF_FLOOR, PART_OF_BUILDING],
        cypher="""
        MATCH (r:Room)-[:PART_OF_FLOOR]->(f:Floor)-[:PART_OF_BUILDING]->(b:Building)
        RETURN
            r.id AS RoomId,
            r.name AS RoomName,
            f.id AS FloorId,
            f.name AS FloorName,
            b.id AS BuildingId,
            b.name AS BuildingName,
            r.temperature AS Temperature,
            r.humidity AS Humidity,
            r.co2 AS CO2,
            floor(50 + (r.temperature - 72) + (r.humidity - 42)
                  + CASE WHEN r.co2 > 500 THEN (r.co2 - 500) / 25 ELSE 0 END) AS ComfortLevel
        """,
    ),
    # The building's overall comfort: the average of each floor's average.
    Query(
        id=BUILDING_COMFORT_LEVEL,
        key="BuildingId",
        joins=[PART_OF_FLOOR, PART_OF_BUILDING],
        cypher="""
        MATCH (r:Room)-[:PART_OF_FLOOR]->(f:Floor)-[:PART_OF_BUILDING]->(b:Building)
        WITH b, f,
            floor(50 + (r.temperature - 72) + (r.humidity - 42)
                  + CASE WHEN r.co2 > 500 THEN (r.co2 - 500) / 25 ELSE 0 END) AS RoomComfortLevel
        WITH b, avg(RoomComfortLevel) AS FloorComfortLevel
        WITH b, avg(FloorComfortLevel) AS ComfortLevel
        RETURN b.id AS BuildingId, ComfortLevel
        """,
    ),
    # Each floor's comfort: the average of the rooms on it.
    Query(
        id=FLOOR_COMFORT_LEVEL,
        key="FloorId",
        joins=[PART_OF_FLOOR],
        cypher="""
        MATCH (r:Room)-[:PART_OF_FLOOR]->(f:Floor)
        WITH f,
            floor(50 + (r.temperature - 72) + (r.humidity - 42)
                  + CASE WHEN r.co2 > 500 THEN (r.co2 - 500) / 25 ELSE 0 END) AS RoomComfortLevel
        WITH f, avg(RoomComfortLevel) AS ComfortLevel
        RETURN f.id AS FloorId, ComfortLevel
        """,
    ),
    # Only the rooms whose comfort is outside the 40-50 band.
    Query(
        id=ROOM_ALERT,
        key="RoomId",
        cypher="""
        MATCH (r:Room)
        WITH r.id AS RoomId, r.name AS RoomName,
            floor(50 + (r.temperature - 72) + (r.humidity - 42)
                  + CASE WHEN r.co2 > 500 THEN (r.co2 - 500) / 25 ELSE 0 END) AS ComfortLevel
        WHERE ComfortLevel < 40 OR ComfortLevel > 50
        RETURN RoomId, RoomName, ComfortLevel
        """,
    ),
    # Only the floors whose average comfort is outside the 40-50 band.
    Query(
        id=FLOOR_ALERT,
        key="FloorId",
        joins=[PART_OF_FLOOR],
        cypher="""
        MATCH (r:Room)-[:PART_OF_FLOOR]->(f:Floor)
        WITH f,
            floor(50 + (r.temperature - 72) + (r.humidity - 42)
                  + CASE WHEN r.co2 > 500 THEN (r.co2 - 500) / 25 ELSE 0 END) AS RoomComfortLevel
        WITH f, avg(RoomComfortLevel) AS ComfortLevel
        WHERE ComfortLevel < 40 OR ComfortLevel > 50
        RETURN f.id AS FloorId, f.name AS FloorName, ComfortLevel
        """,
    ),
    # The building, only while its overall comfort is outside the 40-50 band.
    Query(
        id=BUILDING_ALERT,
        key="BuildingId",
        joins=[PART_OF_FLOOR, PART_OF_BUILDING],
        cypher="""
        MATCH (r:Room)-[:PART_OF_FLOOR]->(f:Floor)-[:PART_OF_BUILDING]->(b:Building)
        WITH b, f,
            floor(50 + (r.temperature - 72) + (r.humidity - 42)
                  + CASE WHEN r.co2 > 500 THEN (r.co2 - 500) / 25 ELSE 0 END) AS RoomComfortLevel
        WITH b, f, avg(RoomComfortLevel) AS FloorComfortLevel
        WITH b, avg(FloorComfortLevel) AS ComfortLevel
        WHERE ComfortLevel < 40 OR ComfortLevel > 50
        RETURN b.id AS BuildingId, b.name AS BuildingName, ComfortLevel
        """,
    ),
]

# =============================================================================
# The engine.
# =============================================================================

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
        # Which RETURN column identifies each query's rows, looked up by query id.
        self._key_by_id = {query.id: query.key for query in QUERIES}
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

        for query in QUERIES:
            await self._drasi.add_query(query.id, query.cypher, ["db"], joins=query.joins or None)
        for query in QUERIES:
            await self._drasi.wait_for_query(query.id)

        # Prime the snapshot from the bootstrapped result sets, then let the
        # reaction keep it current.
        for query in QUERIES:
            rows = await self._drasi.get_query_results(query.id)
            with self._lock:
                self._results[query.id] = {row[query.key]: row for row in rows}
        self._room_ids = await self._load_room_ids()

        await self._drasi.add_python_reaction(
            "ui", [query.id for query in QUERIES], self._on_results
        )

    def _on_results(self, event: QueryResultEvent) -> None:
        """Apply a batch of diffs to the snapshot.

        ``add_python_reaction`` calls this synchronously. Every diff carries the
        affected row in ``data`` (for an UPDATE it equals ``after``), so the
        snapshot is maintained by row identity: upsert on ADD/UPDATE, drop on
        DELETE. Result sets are tiny, so this stays cheap.
        """
        query_id = event["query_id"]
        key_field = self._key_by_id[query_id]
        with self._lock:
            store = self._results.setdefault(query_id, {})
            for diff in event["results"]:
                match diff:
                    case {"type": "DELETE", "data": dict() as row}:
                        store.pop(row[key_field], None)
                    case {"after": dict() as row} | {"data": dict() as row}:
                        # ADD / UPDATE / aggregation: `after` is the new state
                        # (aggregation diffs carry a null `data`), `data` covers ADD.
                        store[row[key_field]] = row
            self._version += 1

    async def _load_room_ids(self) -> list[str]:
        def _query() -> list[str]:
            with psycopg.connect(**PSYCOPG_CONNECTION) as conn:
                with conn.cursor() as cur:
                    cur.execute('SELECT id FROM "Room" ORDER BY id')
                    return [row[0] for row in cur.fetchall()]

        return await asyncio.get_running_loop().run_in_executor(None, _query)

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
            self._sim_task = asyncio.create_task(self._simulate())
            self._simulation = True
        elif not enabled and self._sim_task is not None:
            self._sim_task.cancel()
            self._sim_task = None
            self._simulation = False

    async def _simulate(self) -> None:
        loop = asyncio.get_running_loop()
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
