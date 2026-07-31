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

"""The six continuous queries that power the demo.

Four are single-source filtered lists that split the orders and vehicles by
state, so a row hops from one panel to another the instant it changes. Two join
across *both* databases through a synthetic join on license plate:

    delivery : an order is 'ready' AND its driver's vehicle is at the 'Curbside'
    delay    : a driver has waited at the 'Curbside' for over 10s while the order
               is still being prepared (uses the temporal drasi.trueFor)

Each query is written out in full so you can read exactly what Drasi runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Source ids (one per database).
RETAIL_OPS = "retail-ops"  # PostgreSQL: orders
PHYSICAL_OPS = "physical-ops"  # MySQL: vehicles

# --- Synthetic join ----------------------------------------------------------
# There is no foreign key between the two databases. Drasi creates the
# relationship in the query, matching a vehicle to an order by equal plate.
PICKUP_BY = {
    "id": "PICKUP_BY",
    "keys": [
        {"label": "vehicles", "property": "plate"},
        {"label": "orders", "property": "plate"},
    ],
}

# --- Query ids ---------------------------------------------------------------
# The UI reads each query's result set from the snapshot by these ids.

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


# Orders still being prepared (status != 'ready').
ORDERS_PREPARING_QUERY = Query(
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
)

# Orders that are ready for pickup (status = 'ready').
ORDERS_READY_QUERY = Query(
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
)

# Vehicles still in the parking lot (location = 'Parking').
VEHICLES_PARKING_QUERY = Query(
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
)

# Vehicles waiting at the curb (location = 'Curbside').
VEHICLES_CURBSIDE_QUERY = Query(
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
)

# Matched orders: ready AND the driver's vehicle is at the curbside. Joins the
# PostgreSQL order to the MySQL vehicle by plate. drasi.changeDateTime exposes the
# wall-clock time of each change; drasi.listMax picks the later of the two.
DELIVERY_QUERY = Query(
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
)

# Delayed orders: a driver has been at the curbside for over 10 seconds while the
# order is still not ready. drasi.trueFor schedules a future re-evaluation and
# fires the instant the condition has held for the given duration.
DELAY_QUERY = Query(
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
)

# The engine registers these in order and subscribes one reaction to them all.
QUERIES = [
    ORDERS_PREPARING_QUERY,
    ORDERS_READY_QUERY,
    VEHICLES_PARKING_QUERY,
    VEHICLES_CURBSIDE_QUERY,
    DELIVERY_QUERY,
    DELAY_QUERY,
]
