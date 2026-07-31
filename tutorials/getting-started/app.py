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

"""Getting Started -- a console app driven by a Drasi Python reaction.

Run it with:

    python app.py

The whole demo is this one file. It connects Drasi's PostgreSQL source to the
tutorial's `message` table, starts three continuous queries, and registers a
single Python reaction that prints each result-set change to the console. Then
it stays running and watches. There is no UI and no prompt: you drive changes by
running SQL directly against the database (with `docker exec ... psql`, shown in
the tutorial) and watch the queries react here in real time. Press Ctrl+C to stop.
"""

from __future__ import annotations

import os

# Quiet the engine's default INFO logging so it doesn't drown out the reaction's
# output. Set RUST_LOG=info (or debug) to see what the engine is doing. Must run
# before ``drasi`` is imported.
os.environ.setdefault("RUST_LOG", "warn")

import asyncio  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from typing import Any  # noqa: E402

from drasi import Drasi  # noqa: E402
from drasi.types import QueryResultEvent  # noqa: E402

# --- The source -------------------------------------------------------------
# Connection settings for the tutorial's PostgreSQL database, read from the
# environment with the same defaults the database uses.
POSTGRES = {
    "host": os.environ.get("POSTGRES_HOST", "localhost"),
    "port": int(os.environ.get("POSTGRES_PORT", "5752")),
    "database": os.environ.get("POSTGRES_DATABASE", "getting_started"),
    "user": os.environ.get("POSTGRES_USER", "drasi_user"),
    "password": os.environ.get("POSTGRES_PASSWORD", "drasi_password"),
}

# The Postgres source streams changes from the `message` table via logical
# replication (CDC). The table is schema-qualified here (public.message) while
# tableKeys uses the bare name; the node label Drasi sees is the bare name, so
# the Cypher matches (m:message).
SOURCE_CONFIG = {
    **POSTGRES,
    "sslMode": "prefer",
    "tables": ["public.message"],
    "tableKeys": [{"table": "message", "keyColumns": ["messageid"]}],
    "slotName": "drasi_getting_started_slot",
    "publicationName": "drasi_getting_started_pub",
}
# The bootstrap provider loads the rows that already exist when a query starts.
BOOTSTRAP_CONFIG = {"kind": "postgres", **POSTGRES}

# How long a sender can be quiet before inactive-people flags them (matches the
# duration in the inactive-people query below). Shown in the startup banner.
INACTIVITY_SECONDS = 20


def _row(row: dict[str, Any]) -> str:
    """Render a result row as a compact, readable `key=value` string."""
    return "  ".join(f"{key}={value!r}" for key, value in row.items())


def _stamp() -> str:
    return time.strftime("%H:%M:%S")


def on_change(event: QueryResultEvent) -> None:
    """Print each way a query's result set changed (the console 'reaction')."""
    query_id = event["query_id"]
    for diff in event["results"]:
        match diff:
            case {"type": "ADD", "data": data}:
                print(f"[{_stamp()}] [{query_id}] + {_row(data)}")
            case {"type": "DELETE", "data": data}:
                print(f"[{_stamp()}] [{query_id}] - {_row(data)}")
            case {"type": "UPDATE" | "aggregation", "before": before, "after": after}:
                print(f"[{_stamp()}] [{query_id}] ~ {_row(before)} -> {_row(after)}")


async def main() -> None:
    # Flush each line as it is printed, so the reaction's output appears live
    # even when the app's output is piped to a file rather than a terminal.
    sys.stdout.reconfigure(line_buffering=True)

    async with await Drasi.create("getting-started") as drasi:
        print("Starting Drasi: installing plugins and connecting to PostgreSQL...")
        await drasi.install_plugin("source/postgres")
        await drasi.install_plugin("bootstrap/postgres")
        await drasi.start()

        await drasi.add_source("postgres", "messages", SOURCE_CONFIG, bootstrap=BOOTSTRAP_CONFIG)

        # Add the three continuous queries, in place. They build up in
        # complexity: a filter, an aggregation, and a temporal query that
        # detects the *absence* of change.

        # Filter: messages whose text is exactly "Hello World", and who sent them.
        await drasi.add_query(
            "hello-world-from",
            """
            MATCH (m:message)
            WHERE m.message = 'Hello World'
            RETURN m.messageid AS MessageId, m.sender AS MessageFrom
            """,
            ["messages"],
        )

        # Aggregation: how many times each distinct message has been sent.
        await drasi.add_query(
            "message-count",
            """
            MATCH (m:message)
            RETURN m.message AS Message, count(m) AS Frequency
            """,
            ["messages"],
        )

        # Absence of change: senders who have not sent a message in the last 20
        # seconds. drasi.trueLater schedules a future re-evaluation so a sender
        # appears the instant they cross the threshold, not only when some other
        # change happens.
        await drasi.add_query(
            "inactive-people",
            """
            MATCH (m:message)
            WITH m.sender AS MessageFrom, max(drasi.changeDateTime(m)) AS LastMessageTimestamp
            WHERE LastMessageTimestamp <= datetime.realtime() - duration({ seconds: 20 })
               OR drasi.trueLater(
                    LastMessageTimestamp <= datetime.realtime() - duration({ seconds: 20 }),
                    LastMessageTimestamp + duration({ seconds: 20 })
                  )
            RETURN MessageFrom, LastMessageTimestamp
            """,
            ["messages"],
        )

        # Wait for all three to bootstrap their initial result sets.
        query_ids = ["hello-world-from", "message-count", "inactive-people"]
        for query_id in query_ids:
            await drasi.wait_for_query(query_id, timeout=60)

        # Show the state each query bootstrapped from the existing rows.
        print("\n=== Initial results ===")
        for query_id in query_ids:
            rows = await drasi.get_query_results(query_id)
            print(f"\n[{query_id}] {len(rows)} row(s):")
            for row in rows:
                print(f"  {_row(row)}")

        # From here on, print changes as they arrive.
        await drasi.add_python_reaction("console", query_ids, on_change)

        print(
            f"\n=== Watching for changes (Ctrl+C to stop) ===\n"
            f"Add or delete messages by running SQL against the database "
            f"(docker exec ... psql) and watch the queries react. A sender "
            f"appears in inactive-people once they have been quiet for "
            f"{INACTIVITY_SECONDS}s.\n"
        )
        await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
