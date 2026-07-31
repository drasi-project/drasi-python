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

Everything the demo needs on the Drasi side lives in this one file: the two
databases' connection settings and source configs, the synthetic join, the six
continuous queries, and the ``CurbsideEngine`` that wires them together.

The engine runs Drasi on its own asyncio event loop in a background daemon
thread (created once, cached by Streamlit), and a single **Python reaction** over
all six queries keeps a thread-safe snapshot the UI renders. Drasi reads changes
from a PostgreSQL ``orders`` table and a MySQL ``vehicles`` table and joins them
by license plate. The UI's controls write order changes to Postgres (via
``psycopg``) and vehicle changes to MySQL (via ``PyMySQL``); Drasi observes both
through CDC. Each write is also appended to an in-memory activity log the UI shows.
"""

from __future__ import annotations

import os

# Quiet the engine's default INFO logging. Must run before ``drasi`` is imported.
os.environ.setdefault("RUST_LOG", "warn")

import asyncio  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from collections import deque  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from typing import Any  # noqa: E402

import psycopg  # noqa: E402
import pymysql  # noqa: E402

from drasi import Drasi  # noqa: E402
from drasi.types import QueryResultEvent  # noqa: E402

# =============================================================================
# Configuration -- two databases, read from the environment with defaults.
# =============================================================================

# --- PostgreSQL (orders) ---
POSTGRES = {
    "host": os.environ.get("POSTGRES_HOST", "localhost"),
    "port": int(os.environ.get("POSTGRES_PORT", "5742")),
    "database": os.environ.get("POSTGRES_DATABASE", "RetailOperations"),
    "user": os.environ.get("POSTGRES_USER", "drasi_user"),
    "password": os.environ.get("POSTGRES_PASSWORD", "drasi_password"),
}
# The Postgres source creates its own replication slot on startup and reuses the
# publication created by database/postgres-init.sql.
POSTGRES_SOURCE_CONFIG = {
    **POSTGRES,
    "sslMode": "prefer",
    "tables": ["public.orders"],
    "tableKeys": [{"table": "orders", "keyColumns": ["id"]}],
    "slotName": "drasi_curbside_slot",
    "publicationName": "drasi_curbside_pub",
}
POSTGRES_BOOTSTRAP_CONFIG = {"kind": "postgres", **POSTGRES}
# psycopg spells the database key ``dbname``; the UI writes order status changes
# through this connection so Drasi observes them via logical replication.
PSYCOPG_CONNECTION = {
    "host": POSTGRES["host"],
    "port": POSTGRES["port"],
    "dbname": POSTGRES["database"],
    "user": POSTGRES["user"],
    "password": POSTGRES["password"],
}

# --- MySQL (vehicles) ---
MYSQL = {
    "host": os.environ.get("MYSQL_HOST", "localhost"),
    "port": int(os.environ.get("MYSQL_PORT", "3309")),
    "database": os.environ.get("MYSQL_DATABASE", "PhysicalOperations"),
    "user": os.environ.get("MYSQL_USER", "drasi_user"),
    "password": os.environ.get("MYSQL_PASSWORD", "drasi_password"),
}
# The MySQL source streams the binlog. TLS is disabled on the tutorial container,
# so the source connects in plaintext. Unlike Postgres, the MySQL bootstrap
# provider takes its own connection settings (and does not accept sslMode).
MYSQL_SOURCE_CONFIG = {
    **MYSQL,
    "sslMode": "disabled",
    "tables": ["vehicles"],
    "tableKeys": [{"table": "vehicles", "keyColumns": ["plate"]}],
}
MYSQL_BOOTSTRAP_CONFIG = {
    "kind": "mysql",
    **MYSQL,
    "tables": ["vehicles"],
    "tableKeys": [{"table": "vehicles", "keyColumns": ["plate"]}],
}
# PyMySQL spells the database key ``database``; the UI writes vehicle location
# changes through this connection so Drasi observes them via the binlog.
PYMYSQL_CONNECTION = {
    "host": MYSQL["host"],
    "port": MYSQL["port"],
    "database": MYSQL["database"],
    "user": MYSQL["user"],
    "password": MYSQL["password"],
    "autocommit": True,
}

ORDER_PREPARING = "preparing"
VEHICLE_PARKING = "Parking"

# How long (matching the delay query) a curbside vehicle waits on an unready order
# before it is flagged as delayed. Shown in the UI copy.
DELAY_SECONDS = 10
# How many recent SQL writes to keep in the activity log.
ACTIVITY_LOG_SIZE = 20

# =============================================================================
# The six continuous queries.
# =============================================================================

# Source ids (one per database).
RETAIL_OPS = "retail-ops"  # PostgreSQL: orders
PHYSICAL_OPS = "physical-ops"  # MySQL: vehicles

# There is no foreign key between the two databases. Drasi creates the
# relationship in the query, matching a vehicle to an order by equal plate.
PICKUP_BY = {
    "id": "PICKUP_BY",
    "keys": [
        {"label": "vehicles", "property": "plate"},
        {"label": "orders", "property": "plate"},
    ],
}

# Query ids -- the UI reads each query's result set from the snapshot by these.
ORDERS_PREPARING = "orders-preparing"
ORDERS_READY = "orders-ready"
VEHICLES_PARKING = "vehicles-parking"
VEHICLES_CURBSIDE = "vehicles-curbside"
DELIVERY = "delivery"
DELAY = "delay"


@dataclass(frozen=True)
class Query:
    """One continuous query: how to register it and how to index its rows."""

    id: str
    key: str  # the RETURN column that identifies each row (its primary key)
    sources: list[str]  # the source ids this query reads from
    cypher: str
    joins: list[dict[str, Any]] = field(default_factory=list)


# The four single-source list queries split orders and vehicles by state, and the
# two join queries (delivery, delay) relate them across the two databases.
QUERIES = [
    # Orders still being prepared (status != 'ready').
    Query(
        id=ORDERS_PREPARING,
        key="id",
        sources=[RETAIL_OPS],
        cypher="""
        MATCH (o:orders)
        WHERE o.status <> 'ready'
        RETURN
            o.id AS id,
            o.id AS orderId,
            o.customer_name AS customerName,
            o.driver_name AS driverName,
            o.plate AS plate,
            o.status AS status
        """,
    ),
    # Orders that are ready for pickup (status = 'ready').
    Query(
        id=ORDERS_READY,
        key="id",
        sources=[RETAIL_OPS],
        cypher="""
        MATCH (o:orders)
        WHERE o.status = 'ready'
        RETURN
            o.id AS id,
            o.id AS orderId,
            o.customer_name AS customerName,
            o.driver_name AS driverName,
            o.plate AS plate,
            o.status AS status
        """,
    ),
    # Vehicles still in the parking lot (location = 'Parking').
    Query(
        id=VEHICLES_PARKING,
        key="id",
        sources=[PHYSICAL_OPS],
        cypher="""
        MATCH (v:vehicles)
        WHERE v.location = 'Parking'
        RETURN
            v.plate AS id,
            v.plate AS plate,
            v.make AS make,
            v.model AS model,
            v.color AS color,
            v.location AS location
        """,
    ),
    # Vehicles waiting at the curb (location = 'Curbside').
    Query(
        id=VEHICLES_CURBSIDE,
        key="id",
        sources=[PHYSICAL_OPS],
        cypher="""
        MATCH (v:vehicles)
        WHERE v.location = 'Curbside'
        RETURN
            v.plate AS id,
            v.plate AS plate,
            v.make AS make,
            v.model AS model,
            v.color AS color,
            v.location AS location
        """,
    ),
    # Matched orders: ready AND the driver's vehicle is at the curbside. Joins the
    # PostgreSQL order to the MySQL vehicle by plate. drasi.listMax picks the later
    # of the two change times (drasi.changeDateTime).
    Query(
        id=DELIVERY,
        key="id",
        sources=[RETAIL_OPS, PHYSICAL_OPS],
        joins=[PICKUP_BY],
        cypher="""
        MATCH (o:orders)-[:PICKUP_BY]->(v:vehicles)
        WHERE o.status = 'ready' AND v.location = 'Curbside'
        RETURN
            o.id AS id,
            o.id AS orderId,
            o.customer_name AS customerName,
            o.driver_name AS driverName,
            o.plate AS vehicleId,
            v.make AS vehicleMake,
            v.model AS vehicleModel,
            v.color AS vehicleColor,
            v.location AS vehicleLocation,
            drasi.listMax([drasi.changeDateTime(o), drasi.changeDateTime(v)]) AS readyTimestamp
        """,
    ),
    # Delayed orders: a driver has been at the curbside for over 10 seconds while
    # the order is still not ready. drasi.trueFor schedules a future re-evaluation
    # and fires the instant the condition has held for the given duration.
    Query(
        id=DELAY,
        key="orderId",
        sources=[RETAIL_OPS, PHYSICAL_OPS],
        joins=[PICKUP_BY],
        cypher="""
        MATCH (o:orders)-[:PICKUP_BY]->(v:vehicles)
        WHERE o.status <> 'ready'
          AND drasi.trueFor(v.location = 'Curbside', duration({ seconds: 10 }))
        RETURN
            o.id AS orderId,
            o.customer_name AS customerName,
            o.driver_name AS driverName,
            o.plate AS plate,
            drasi.changeDateTime(v) AS waitingSinceTimestamp
        """,
    ),
]

# =============================================================================
# The engine.
# =============================================================================


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
        """Apply a batch of diffs to the snapshot (called synchronously)."""
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
