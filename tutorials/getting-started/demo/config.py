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

"""Configuration for the Getting Started tutorial.

Just enough to point Drasi's PostgreSQL source at the tutorial database, read
from the environment with the same defaults the database uses. The app only
reads and reacts -- it never writes -- so there is no database client here; you
drive changes with SQL run directly against the database.
"""

from __future__ import annotations

import os

POSTGRES = {
    "host": os.environ.get("POSTGRES_HOST", "localhost"),
    "port": int(os.environ.get("POSTGRES_PORT", "5752")),
    "database": os.environ.get("POSTGRES_DATABASE", "getting_started"),
    "user": os.environ.get("POSTGRES_USER", "drasi_user"),
    "password": os.environ.get("POSTGRES_PASSWORD", "drasi_password"),
}

# The Postgres source creates its own replication slot on startup and reuses the
# publication created by database/init.sql. The table is schema-qualified here
# (public.message) while tableKeys uses the bare name; the node label Drasi sees
# is the bare name, so the Cypher matches (m:message).
SOURCE_CONFIG = {
    **POSTGRES,
    "sslMode": "prefer",
    "tables": ["public.message"],
    "tableKeys": [{"table": "message", "keyColumns": ["messageid"]}],
    "slotName": "drasi_getting_started_slot",
    "publicationName": "drasi_getting_started_pub",
}

# The bootstrap provider loads the rows that already exist when the query starts.
BOOTSTRAP_CONFIG = {"kind": "postgres", **POSTGRES}

# The id of the single source the queries read from.
SOURCE_ID = "messages"

# How long a sender can be quiet before inactive-people flags them (matches the
# duration in the query). Shown in the app's startup banner.
INACTIVITY_SECONDS = 20
