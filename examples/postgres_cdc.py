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

Starts a throwaway Postgres in Docker, installs the `source/postgres` plugin,
and prints every change the continuous query sees as rows are inserted, updated
and deleted with plain SQL.

    pip install "testcontainers>=4.15" "psycopg[binary]"
    python examples/postgres_cdc.py

Requires Docker and network access to ghcr.io.
"""

import os

# The engine logs at INFO by default, which drowns out an example's own output.
# Set RUST_LOG=info (or debug) to see what the engine is doing.
os.environ.setdefault("RUST_LOG", "warn")

import asyncio  # noqa: E402

from drasi import Drasi  # noqa: E402

# The source only replicates tables that belong to a publication, and it needs a
# key to correlate a change with an existing row. Without the publication it
# connects and delivers nothing; without the key, updates arrive as duplicate
# inserts and deletes do nothing at all.
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


async def main() -> None:
    try:
        import psycopg
        from testcontainers.community.postgres import PostgresContainer
    except ImportError:
        raise SystemExit(
            'this example needs: pip install "testcontainers>=4.15" "psycopg[binary]"'
        ) from None

    container = PostgresContainer("postgres:16-alpine", driver=None).with_command(
        # Row data only reaches the write-ahead log at the `logical` level.
        "postgres -c wal_level=logical -c max_replication_slots=8 -c max_wal_senders=8"
    )

    print("starting postgres (first run pulls the image)")
    with container as postgres:
        dsn = (
            f"host={postgres.get_container_host_ip()} "
            f"port={postgres.get_exposed_port(5432)} "
            f"dbname={postgres.dbname} user={postgres.username} "
            f"password={postgres.password}"
        )

        def sql(statement: str) -> None:
            with psycopg.connect(dsn, autocommit=True) as connection:
                connection.execute(statement)

        sql(SCHEMA)

        async with await Drasi.create("postgres-demo") as drasi:
            print("installing the postgres source plugin")
            await drasi.install_plugin("source/postgres")
            await drasi.start()

            await drasi.add_source(
                "postgres",
                "db",
                {
                    "host": postgres.get_container_host_ip(),
                    "port": int(postgres.get_exposed_port(5432)),
                    "user": postgres.username,
                    "password": postgres.password,
                    "database": postgres.dbname,
                    "tables": ["public.orders"],
                    # Note: `tables` is schema-qualified but this is not.
                    "tableKeys": [{"table": "orders", "keyColumns": ["id"]}],
                },
            )
            await drasi.add_query("open-orders", OPEN_ORDERS, ["db"])
            await drasi.wait_for_query("open-orders")

            def on_change(event: dict) -> None:
                for diff in event["results"]:
                    if diff["type"] == "ADD":
                        print(f"  + {diff['data']}")
                    elif diff["type"] == "DELETE":
                        print(f"  - {diff['data']}")
                    else:
                        print(f"  ~ {diff['before']} -> {diff['after']}")

            await drasi.add_python_reaction("printer", ["open-orders"], on_change)

            print("\ninserting two orders")
            sql("INSERT INTO orders VALUES (1, 'Ada', 'open'), (2, 'Grace', 'open')")
            await asyncio.sleep(2)

            print("shipping order 1 — it should leave the result set")
            sql("UPDATE orders SET status = 'shipped' WHERE id = 1")
            await asyncio.sleep(2)

            print("deleting order 2")
            sql("DELETE FROM orders WHERE id = 2")
            await asyncio.sleep(2)

            print(f"\nstill open: {await drasi.get_query_results('open-orders')}")


if __name__ == "__main__":
    asyncio.run(main())
