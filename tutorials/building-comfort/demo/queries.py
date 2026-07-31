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

Each query is written out in full below so you can read (or copy) exactly what
Drasi runs. They all compute the same comfort level:

    floor(50 + (temperature - 72) + (humidity - 42)
          + CASE WHEN co2 > 500 THEN (co2 - 500) / 25 ELSE 0 END)

A value between 40 and 50 is comfortable; the seed values (70F, 40%, 10 ppm)
give floor(50 + (70-72) + (40-42) + 0) = 46.

The Room -> Floor -> Building hierarchy is walked through two *synthetic joins*.
Drasi does not read Postgres foreign keys, so each query declares the
relationships it needs. A join is a plain mapping passed to ``add_query``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# --- Synthetic joins ---------------------------------------------------------
# Room.floor_id -> Floor.id, and Floor.building_id -> Building.id.

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

# --- Query ids ---------------------------------------------------------------
# The UI reads each query's result set from the snapshot by these ids.

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


# One row per room, with its comfort level. Drives the building view.
BUILDING_COMFORT_UI_QUERY = Query(
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
)

# The building's overall comfort: the average of each floor's average.
BUILDING_COMFORT_LEVEL_QUERY = Query(
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
)

# Each floor's comfort: the average of the rooms on it.
FLOOR_COMFORT_LEVEL_QUERY = Query(
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
)

# Only the rooms whose comfort is outside the 40-50 band.
ROOM_ALERT_QUERY = Query(
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
)

# Only the floors whose average comfort is outside the 40-50 band.
FLOOR_ALERT_QUERY = Query(
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
)

# The building, only while its overall comfort is outside the 40-50 band.
BUILDING_ALERT_QUERY = Query(
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
)

# The engine registers these in order and subscribes one reaction to them all.
QUERIES = [
    BUILDING_COMFORT_UI_QUERY,
    BUILDING_COMFORT_LEVEL_QUERY,
    FLOOR_COMFORT_LEVEL_QUERY,
    ROOM_ALERT_QUERY,
    FLOOR_ALERT_QUERY,
    BUILDING_ALERT_QUERY,
]
