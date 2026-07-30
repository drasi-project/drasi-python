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

"""The six continuous queries, ported from the Drasi Server tutorial.

Each query computes a comfort level with the same formula. A value between 40
and 50 is comfortable; the seed values (70F, 40%, 10 ppm) give
``floor(50 + (70-72) + (40-42) + 0) = 46``.

The Room -> Floor -> Building hierarchy is walked through two *synthetic joins*.
Drasi does not read Postgres foreign keys, so each query declares the
relationships it needs. In ``drasi-lib`` a join is a ``Join`` mapping, passed to
``add_query(..., joins=[...])`` -- the same shape the Drasi Server YAML uses.
"""

from __future__ import annotations

from typing import Any

# The comfort formula, shared by every query. ``r`` is the Room node.
_COMFORT = (
    "floor( 50 + (r.temperature - 72) + (r.humidity - 42)"
    " + CASE WHEN r.co2 > 500 THEN (r.co2 - 500) / 25 ELSE 0 END )"
)

# Synthetic joins: Room.floor_id -> Floor.id, Floor.building_id -> Building.id.
PART_OF_FLOOR: dict[str, Any] = {
    "id": "PART_OF_FLOOR",
    "keys": [
        {"label": "Room", "property": "floor_id"},
        {"label": "Floor", "property": "id"},
    ],
}
PART_OF_BUILDING: dict[str, Any] = {
    "id": "PART_OF_BUILDING",
    "keys": [
        {"label": "Floor", "property": "building_id"},
        {"label": "Building", "property": "id"},
    ],
}

# Query ids, used both to register the queries and to index the reaction's state.
BUILDING_COMFORT_UI = "building-comfort-ui"
BUILDING_COMFORT_LEVEL = "building-comfort-level-calc"
FLOOR_COMFORT_LEVEL = "floor-comfort-level-calc"
ROOM_ALERT = "room-alert"
FLOOR_ALERT = "floor-alert"
BUILDING_ALERT = "building-alert"


# Each entry: (id, cypher, joins). ``joins`` is empty for queries that match a
# single label. The engine registers them in order.
QUERIES: list[tuple[str, str, list[dict[str, Any]]]] = [
    # Query 1: per-room comfort level (drives the building view).
    (
        BUILDING_COMFORT_UI,
        f"""
        MATCH
          (r:Room)-[:PART_OF_FLOOR]->(f:Floor)-[:PART_OF_BUILDING]->(b:Building)
        WITH
          r, f, b,
          {_COMFORT} AS ComfortLevel
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
          ComfortLevel
        """,
        [PART_OF_FLOOR, PART_OF_BUILDING],
    ),
    # Query 2: overall building comfort (avg of floor averages).
    (
        BUILDING_COMFORT_LEVEL,
        f"""
        MATCH
          (r:Room)-[:PART_OF_FLOOR]->(f:Floor)-[:PART_OF_BUILDING]->(b:Building)
        WITH
          b,
          {_COMFORT} AS RoomComfortLevel
        WITH
          b,
          avg(RoomComfortLevel) AS FloorComfortLevel
        WITH
          b,
          avg(FloorComfortLevel) AS ComfortLevel
        RETURN
          b.id AS BuildingId,
          ComfortLevel
        """,
        [PART_OF_FLOOR, PART_OF_BUILDING],
    ),
    # Query 3: per-floor comfort (avg of the floor's rooms).
    (
        FLOOR_COMFORT_LEVEL,
        f"""
        MATCH
          (r:Room)-[:PART_OF_FLOOR]->(f:Floor)
        WITH
          f,
          {_COMFORT} AS RoomComfortLevel
        WITH
          f,
          avg(RoomComfortLevel) AS ComfortLevel
        RETURN
          f.id AS FloorId,
          ComfortLevel
        """,
        [PART_OF_FLOOR],
    ),
    # Query 4: rooms outside the comfortable band (40-50).
    (
        ROOM_ALERT,
        f"""
        MATCH
          (r:Room)
        WITH
          r.id AS RoomId,
          r.name AS RoomName,
          {_COMFORT} AS ComfortLevel
        WHERE ComfortLevel < 40 OR ComfortLevel > 50
        RETURN
          RoomId, RoomName, ComfortLevel
        """,
        [],
    ),
    # Query 5: floors whose average comfort is outside 40-50.
    (
        FLOOR_ALERT,
        f"""
        MATCH
          (r:Room)-[:PART_OF_FLOOR]->(f:Floor)
        WITH
          f,
          {_COMFORT} AS RoomComfortLevel
        WITH
          f,
          avg(RoomComfortLevel) AS ComfortLevel
        WHERE
          ComfortLevel < 40 OR ComfortLevel > 50
        RETURN
          f.id AS FloorId,
          f.name AS FloorName,
          ComfortLevel
        """,
        [PART_OF_FLOOR],
    ),
    # Query 6: the building when its overall comfort is outside 40-50.
    (
        BUILDING_ALERT,
        f"""
        MATCH
          (r:Room)-[:PART_OF_FLOOR]->(f:Floor)-[:PART_OF_BUILDING]->(b:Building)
        WITH
          f, b,
          {_COMFORT} AS RoomComfortLevel
        WITH
          f, b,
          avg(RoomComfortLevel) AS FloorComfortLevel
        WITH
          b,
          avg(FloorComfortLevel) AS ComfortLevel
        WHERE
          ComfortLevel < 40 OR ComfortLevel > 50
        RETURN
          b.id AS BuildingId,
          b.name AS BuildingName,
          ComfortLevel
        """,
        [PART_OF_FLOOR, PART_OF_BUILDING],
    ),
]

# The query ids the UI reaction subscribes to (all of them).
ALL_QUERY_IDS = [q[0] for q in QUERIES]

# The primary-key field of each query's rows. The reaction keeps a snapshot of
# every query keyed by this field, so it can apply ADD/UPDATE/DELETE diffs by row
# identity rather than rescanning.
KEY_FIELDS: dict[str, str] = {
    BUILDING_COMFORT_UI: "RoomId",
    BUILDING_COMFORT_LEVEL: "BuildingId",
    FLOOR_COMFORT_LEVEL: "FloorId",
    ROOM_ALERT: "RoomId",
    FLOOR_ALERT: "FloorId",
    BUILDING_ALERT: "BuildingId",
}
