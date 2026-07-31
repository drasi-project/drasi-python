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

It connects Drasi's PostgreSQL source to the tutorial's `message` table, starts
three continuous queries, and registers a single **Python reaction** that prints
each result-set change to the console. Then it stays running and watches. There
is no UI and no prompt: you drive changes by running SQL directly against the
database (see scripts/add-message.sh and scripts/delete-message.sh) and watch the
queries react here in real time. Press Ctrl+C to stop.
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

from demo.config import (  # noqa: E402
    BOOTSTRAP_CONFIG,
    INACTIVITY_SECONDS,
    SOURCE_CONFIG,
    SOURCE_ID,
)
from demo.queries import QUERIES  # noqa: E402

from drasi import Drasi  # noqa: E402
from drasi.types import QueryResultEvent  # noqa: E402


def _row(row: dict[str, Any]) -> str:
    """Render a result row as a compact, readable `key=value` string."""
    return "  ".join(f"{key}={value!r}" for key, value in row.items())


def _stamp() -> str:
    return time.strftime("%H:%M:%S")


def on_change(event: QueryResultEvent) -> None:
    """Print each way a query's result set changed (the console 'reaction')."""
    query_id = event["query_id"]
    for diff in event["results"]:
        if diff["type"] == "ADD":
            print(f"[{_stamp()}] [{query_id}] + {_row(diff['data'])}")
        elif diff["type"] == "DELETE":
            print(f"[{_stamp()}] [{query_id}] - {_row(diff['data'])}")
        else:  # UPDATE
            print(f"[{_stamp()}] [{query_id}] ~ {_row(diff['before'])} -> {_row(diff['after'])}")


async def main() -> None:
    # Flush each line as it is printed, so the reaction's output appears live
    # even when the app's output is piped to a file rather than a terminal.
    sys.stdout.reconfigure(line_buffering=True)

    async with await Drasi.create("getting-started") as drasi:
        print("Starting Drasi: installing plugins and connecting to PostgreSQL...")
        await drasi.install_plugin("source/postgres")
        await drasi.install_plugin("bootstrap/postgres")
        await drasi.start()

        await drasi.add_source("postgres", SOURCE_ID, SOURCE_CONFIG, bootstrap=BOOTSTRAP_CONFIG)

        for query in QUERIES:
            await drasi.add_query(query.id, query.cypher, [SOURCE_ID])
        for query in QUERIES:
            await drasi.wait_for_query(query.id, timeout=60)

        # Show the state each query bootstrapped from the existing rows.
        print("\n=== Initial results ===")
        for query in QUERIES:
            rows = await drasi.get_query_results(query.id)
            print(f"\n[{query.id}] {len(rows)} row(s):")
            for row in rows:
                print(f"  {_row(row)}")

        # From here on, print changes as they arrive.
        await drasi.add_python_reaction("console", [q.id for q in QUERIES], on_change)

        print(
            f"\n=== Watching for changes (Ctrl+C to stop) ===\n"
            f"Add or delete messages with SQL (scripts/add-message.sh, "
            f"scripts/delete-message.sh) and watch the queries react. A sender "
            f"appears in inactive-people once they have been quiet for "
            f"{INACTIVITY_SECONDS}s.\n"
        )
        await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
