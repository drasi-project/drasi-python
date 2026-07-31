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

The same pattern as the Building Comfort tutorial: the Drasi engine runs on its
own asyncio event loop in a background daemon thread (created once, cached by
Streamlit), and a single **Python reaction** over all six queries keeps a
thread-safe snapshot the UI renders.

What is new here is that there are **two** databases. Drasi reads changes from a
PostgreSQL `orders` table and a MySQL `vehicles` table and joins them by license
plate. The UI's controls write order changes to Postgres (via ``psycopg``) and
vehicle changes to MySQL (via ``PyMySQL``); Drasi observes both through CDC. Each
write is also appended to an in-memory activity log the UI shows.
"""

from __future__ import annotations

import os

# Quiet the engine's default INFO logging. Must run before ``drasi`` is imported.
os.environ.setdefault("RUST_LOG", "warn")

import asyncio  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from collections import deque  # noqa: E402
from typing import Any  # noqa: E402

import psycopg  # noqa: E402
import pymysql  # noqa: E402

from drasi import Drasi  # noqa: E402
from drasi.types import QueryResultEvent  # noqa: E402

from .config import (  # noqa: E402
    ACTIVITY_LOG_SIZE,
    MYSQL_BOOTSTRAP_CONFIG,
    MYSQL_SOURCE_CONFIG,
    ORDER_PREPARING,
    POSTGRES_BOOTSTRAP_CONFIG,
    POSTGRES_SOURCE_CONFIG,
    PSYCOPG_CONNECTION,
    PYMYSQL_CONNECTION,
    VEHICLE_PARKING,
)
from .queries import PHYSICAL_OPS, QUERIES, RETAIL_OPS  # noqa: E402


class CurbsideEngine:
    """Runs Drasi over two databases and exposes a thread-safe snapshot."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Per query: a dict keyed by that query's primary-key field. The reaction
        # applies diffs into it; the UI reads a snapshot of the values.
        self._results: dict[str, dict[Any, dict[str, Any]]] = {}
        # Which RETURN column identifies each query's rows, looked up by query id.
        self._key_by_id = {query.id: query.key for query in QUERIES}
        self._version = 0
        # Recent SQL writes, newest last: {"db": ..., "sql": ..., "at": ...}.
        self._activity: deque[dict[str, Any]] = deque(maxlen=ACTIVITY_LOG_SIZE)

        self._loop: asyncio.AbstractEventLoop | None = None
        self._drasi: Drasi | None = None

        self._ready = threading.Event()
        self._error: BaseException | None = None

        self._thread = threading.Thread(target=self._run, name="drasi-curbside-engine", daemon=True)
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
        self._drasi = await Drasi.create("curbside-pickup")

        for plugin in (
            "source/postgres",
            "bootstrap/postgres",
            "source/mysql",
            "bootstrap/mysql",
        ):
            await self._drasi.install_plugin(plugin)
        await self._drasi.start()

        # Two sources: PostgreSQL orders and MySQL vehicles.
        await self._drasi.add_source(
            "postgres", RETAIL_OPS, POSTGRES_SOURCE_CONFIG, bootstrap=POSTGRES_BOOTSTRAP_CONFIG
        )
        await self._drasi.add_source(
            "mysql", PHYSICAL_OPS, MYSQL_SOURCE_CONFIG, bootstrap=MYSQL_BOOTSTRAP_CONFIG
        )

        for query in QUERIES:
            await self._drasi.add_query(
                query.id, query.cypher, query.sources, joins=query.joins or None
            )
        for query in QUERIES:
            await self._drasi.wait_for_query(query.id, timeout=60)

        # Prime the snapshot from the bootstrapped result sets, then let the
        # reaction keep it current.
        for query in QUERIES:
            rows = await self._drasi.get_query_results(query.id)
            with self._lock:
                self._results[query.id] = {row[query.key]: row for row in rows}

        await self._drasi.add_python_reaction(
            "ui", [query.id for query in QUERIES], self._on_results
        )

    def _on_results(self, event: QueryResultEvent) -> None:
        """Apply a batch of diffs to the snapshot (called synchronously).

        Every diff carries the affected row in ``data`` (for an UPDATE it equals
        ``after``), so the snapshot is kept by row identity: upsert on ADD/UPDATE,
        drop on DELETE.
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

    # -- readiness -----------------------------------------------------------

    def wait_ready(self, timeout: float = 240.0) -> None:
        """Block until the engine is running, raising if it failed to start."""
        if not self._ready.wait(timeout):
            raise TimeoutError("the Drasi engine did not start in time")
        if self._error is not None:
            raise RuntimeError(f"the Drasi engine failed to start: {self._error}")

    # -- reads (any thread) --------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Return the current result set of every query, plus the activity log."""
        with self._lock:
            results = {qid: list(store.values()) for qid, store in self._results.items()}
            activity = list(self._activity)
            return {
                "version": self._version,
                "results": results,
                "activity": activity,
                "error": str(self._error) if self._error else None,
            }

    # -- writes (any thread -> a database, observed via CDC) -----------------

    def set_order_status(self, order_id: int, status: str) -> None:
        """Update one order's status in PostgreSQL."""
        with psycopg.connect(**PSYCOPG_CONNECTION) as conn:
            conn.execute("UPDATE orders SET status = %s WHERE id = %s", (status, order_id))
        self._log("PostgreSQL", f"UPDATE orders SET status='{status}' WHERE id={order_id};")

    def set_vehicle_location(self, plate: str, location: str) -> None:
        """Update one vehicle's location in MySQL."""
        conn = pymysql.connect(**PYMYSQL_CONNECTION)
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE vehicles SET location = %s WHERE plate = %s", (location, plate))
        finally:
            conn.close()
        self._log("MySQL", f"UPDATE vehicles SET location='{location}' WHERE plate='{plate}';")

    def reset(self) -> None:
        """Return everything to the start: all orders preparing, all parked."""
        with psycopg.connect(**PSYCOPG_CONNECTION) as conn:
            conn.execute(
                "UPDATE orders SET status = %s WHERE status <> %s",
                (ORDER_PREPARING, ORDER_PREPARING),
            )
        conn2 = pymysql.connect(**PYMYSQL_CONNECTION)
        try:
            with conn2.cursor() as cur:
                cur.execute(
                    "UPDATE vehicles SET location = %s WHERE location <> %s",
                    (VEHICLE_PARKING, VEHICLE_PARKING),
                )
        finally:
            conn2.close()
        self._log("PostgreSQL", f"UPDATE orders SET status='{ORDER_PREPARING}';")
        self._log("MySQL", f"UPDATE vehicles SET location='{VEHICLE_PARKING}';")

    def _log(self, db: str, sql: str) -> None:
        with self._lock:
            self._activity.append({"db": db, "sql": sql, "at": time.strftime("%H:%M:%S")})
