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

"""Configuration for the Building Comfort tutorial.

Everything the demo needs to reach Postgres, plus the demo's constants, read
from the environment with the same defaults the tutorial's database uses. Copy
``.env.example`` to ``.env`` (and ``source`` it) to override any of them.
"""

from __future__ import annotations

import os

# --- PostgreSQL connection ---------------------------------------------------

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

# --- Drasi source / bootstrap ------------------------------------------------

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

# --- Demo constants ----------------------------------------------------------

# Comfortable defaults. floor(50 + (70-72) + (40-42) + 0) = 46, inside 40-50.
COMFORT_DEFAULTS = {"temperature": 70, "humidity": 40, "co2": 10}

# The comfortable band. A room, floor or building outside it raises an alert.
COMFORT_MIN = 40
COMFORT_MAX = 50

# How often simulation mode assigns a random room new readings, in seconds.
SIMULATION_INTERVAL_S = float(os.environ.get("SIMULATION_INTERVAL_S", "3"))
