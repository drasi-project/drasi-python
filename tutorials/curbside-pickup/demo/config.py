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

"""Configuration for the Curbside Pickup tutorial.

Two independent databases: PostgreSQL holds the orders (Retail Operations) and
MySQL holds the vehicles (Physical Operations). This module has the connection
settings for both -- for Drasi's source plugins and for the direct SQL writes the
UI makes (psycopg for Postgres, PyMySQL for MySQL) -- read from the environment
with the same defaults the tutorial's databases use.
"""

from __future__ import annotations

import os

# --- PostgreSQL (orders) -----------------------------------------------------

POSTGRES = {
    "host": os.environ.get("POSTGRES_HOST", "localhost"),
    "port": int(os.environ.get("POSTGRES_PORT", "5742")),
    "database": os.environ.get("POSTGRES_DATABASE", "RetailOperations"),
    "user": os.environ.get("POSTGRES_USER", "drasi_user"),
    "password": os.environ.get("POSTGRES_PASSWORD", "drasi_password"),
}

# The Postgres source plugin creates its own replication slot on startup and
# reuses the publication created by database/postgres-init.sql.
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

# --- MySQL (vehicles) --------------------------------------------------------

MYSQL = {
    "host": os.environ.get("MYSQL_HOST", "localhost"),
    "port": int(os.environ.get("MYSQL_PORT", "3309")),
    "database": os.environ.get("MYSQL_DATABASE", "PhysicalOperations"),
    "user": os.environ.get("MYSQL_USER", "drasi_user"),
    "password": os.environ.get("MYSQL_PASSWORD", "drasi_password"),
}

# The MySQL source streams the binlog. TLS is disabled on the tutorial container,
# so the source must connect in plaintext. Unlike Postgres, the MySQL bootstrap
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

# --- Demo constants ----------------------------------------------------------

ORDER_PREPARING = "preparing"
ORDER_READY = "ready"
VEHICLE_PARKING = "Parking"
VEHICLE_CURBSIDE = "Curbside"

# How long (matching the delay query) a curbside vehicle waits on an unready order
# before it is flagged as delayed. Shown in the UI copy.
DELAY_SECONDS = 10

# How many recent SQL writes to keep in the activity log.
ACTIVITY_LOG_SIZE = 20
