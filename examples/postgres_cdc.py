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

"""React to changes in a real Postgres database.

Installs the `source/postgres` plugin, points it at a database, and prints what
the continuous query sees as rows are inserted, updated and deleted with SQL.

    make example-postgres

Requires Docker and network access to ghcr.io. Starting the database is handled
by `_throwaway_postgres.py`; point `connection` at your own database instead and
the rest of this file is unchanged.
"""

import os

# The engine logs at INFO by default, which drowns out an example's own output.
# Set RUST_LOG=info (or debug) to see what the engine is doing.
os.environ.setdefault("RUST_LOG", "warn")

import asyncio  # noqa: E402

from _throwaway_postgres import throwaway_postgres  # noqa: E402

from drasi import Drasi  # noqa: E402

# Two things here are Drasi's business rather than ordinary schema design.
# The source replicates only tables belonging to a publication: without one it
# connects, reports Running, and delivers nothing. REPLICA IDENTITY FULL makes
# Postgres include the old row in updates and deletes.
SCHEMA = """
CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    customer TEXT NOT NULL,
    status TEXT NOT NULL
);
ALTER TABLE orders REPLICA IDENTITY FULL;
CREATE PUBLICATION drasi_publication FOR TABLE orders;
"""

OPEN_ORDERS = """
MATCH (o:orders)
WHERE o.status = 'open'
RETURN o.id AS id, o.customer AS customer
"""


def on_change(event: dict) -> None:
    """Prints each way the result set changed."""
    for diff in event["results"]:
        if diff["type"] == "ADD":
            print(f"  + {diff['data']}")
        elif diff["type"] == "DELETE":
            print(f"  - {diff['data']}")
        else:
            print(f"  ~ {diff['before']} -> {diff['after']}")


async def main() -> None:
    with throwaway_postgres(SCHEMA) as postgres:
        async with await Drasi.create("postgres-demo") as drasi:
            print("installing the postgres source plugin")
            await drasi.install_plugin("source/postgres")
            await drasi.start()

            await drasi.add_source(
                "postgres",
                "db",
                {
                    **postgres.connection,
                    "tables": ["public.orders"],
                    # Note the asymmetry: `tables` is schema-qualified, this is
                    # not. Qualify it and the key is silently ignored, so
                    # updates arrive as duplicate inserts and deletes do nothing.
                    "tableKeys": [{"table": "orders", "keyColumns": ["id"]}],
                },
            )
            await drasi.add_query("open-orders", OPEN_ORDERS, ["db"])
            await drasi.wait_for_query("open-orders")
            await drasi.add_python_reaction("printer", ["open-orders"], on_change)

            print("\ninserting two orders")
            postgres.sql("INSERT INTO orders VALUES (1, 'Ada', 'open'), (2, 'Grace', 'open')")
            await asyncio.sleep(2)

            print("shipping order 1 — it should leave the result set")
            postgres.sql("UPDATE orders SET status = 'shipped' WHERE id = 1")
            await asyncio.sleep(2)

            print("deleting order 2")
            postgres.sql("DELETE FROM orders WHERE id = 2")
            await asyncio.sleep(2)

            print(f"\nstill open: {await drasi.get_query_results('open-orders')}")


if __name__ == "__main__":
    asyncio.run(main())
