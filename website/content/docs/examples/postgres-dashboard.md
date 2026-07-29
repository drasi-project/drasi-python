---
title: "Postgres dashboard"
linkTitle: "Postgres dashboard"
weight: 10
description: >
  Follow a Postgres table into a live dashboard, using only published plugins.
---

This builds a running dashboard over a Postgres table: rows appear when inserted,
move when updated, and disappear when they stop matching — without polling and without
writing any UI code. Everything comes from the published package and published plugins.

You need Docker and network access to `ghcr.io`.

## The database

Drasi's Postgres source reads the write-ahead log, which only carries row data at the
`logical` level:

```bash
docker run -d --name drasi-demo-pg \
  -e POSTGRES_PASSWORD=drasi -e POSTGRES_USER=drasi -e POSTGRES_DB=drasidemo \
  -p 5433:5432 postgres:16-alpine \
  postgres -c wal_level=logical -c max_replication_slots=8 -c max_wal_senders=8
```

Two details in the schema are Drasi's business rather than ordinary design:

```sql
CREATE TABLE orders (
    id       INTEGER PRIMARY KEY,
    customer TEXT    NOT NULL,
    item     TEXT    NOT NULL,
    amount   NUMERIC(10,2) NOT NULL,
    status   TEXT    NOT NULL
);
ALTER TABLE orders REPLICA IDENTITY FULL;
CREATE PUBLICATION drasi_publication FOR TABLE orders;
```

`REPLICA IDENTITY FULL` makes Postgres include the old row in updates and deletes, so a
query can tell you what changed rather than only what it changed to. The publication is
what the source replicates from. Both are Postgres-side replication setup — the source
plugin's own documentation is what specifies them.

## The program

```python
import asyncio

from drasi import Drasi

POSTGRES = {
    "host": "localhost",
    "port": 5433,
    "user": "drasi",
    "password": "drasi",
    "database": "drasidemo",
}

OPEN_ORDERS = """
MATCH (o:orders)
WHERE o.status = 'open'
RETURN o.id AS id, o.customer AS customer, o.item AS item, o.amount AS amount
"""


async def main() -> None:
    async with await Drasi.create("dashboard-demo") as drasi:
        for plugin in ("source/postgres", "bootstrap/postgres", "reaction/dashboard"):
            await drasi.install_plugin(plugin)

        await drasi.start()

        await drasi.add_source(
            "postgres",
            "db",
            {
                **POSTGRES,
                "tables": ["public.orders"],
                "tableKeys": [{"table": "orders", "keyColumns": ["id"]}],
            },
            bootstrap={"kind": "postgres", **POSTGRES},
        )

        await drasi.add_query("open-orders", OPEN_ORDERS, ["db"])
        await drasi.wait_for_query("open-orders")

        await drasi.add_reaction(
            "dashboard",
            "ui",
            ["open-orders"],
            {
                "host": "0.0.0.0",
                "port": 3000,
                "predefinedDashboards": [
                    {
                        "id": "orders",
                        "name": "Orders",
                        "widgets": [
                            {
                                "id": "open-table",
                                "type": "table",
                                "title": "Open orders",
                                "grid": {"x": 0, "y": 0, "w": 8, "h": 5},
                                "config": {
                                    "queryId": "open-orders",
                                    "columns": ["id", "customer", "item", "amount"],
                                },
                            },
                            {
                                "id": "open-value",
                                "type": "kpi",
                                "title": "Open value",
                                "grid": {"x": 8, "y": 0, "w": 4, "h": 2},
                                "config": {
                                    "queryId": "open-orders",
                                    "valueField": "amount",
                                    "aggregation": "sum",
                                    "label": "total",
                                },
                            },
                        ],
                    }
                ],
            },
        )

        print("dashboard on http://localhost:3000")
        await asyncio.Event().wait()


asyncio.run(main())
```

Open <http://localhost:3000> and the table is already populated.

## Why bootstrap matters here

The source is pure change data capture: it streams the write-ahead log from the point
its replication slot was created, so rows written *before* that are invisible to it. A
query over a table with a million rows in it would start empty and stay wrong.

The `bootstrap=` argument attaches a bootstrap provider, which loads the current
contents when the query subscribes; the change feed takes over from there. Leave it out
and the dashboard starts blank, filling in only as rows happen to be touched — which
looks like the source losing data.

## Watch it update

```bash
psql() { docker exec -i drasi-demo-pg psql -U drasi -d drasidemo -c "$1"; }

psql "INSERT INTO orders VALUES (1,'Ada','Analytical Engine',2400.00,'open')"
psql "UPDATE orders SET status='shipped' WHERE id=1"    # leaves the result set
psql "UPDATE orders SET amount=5000.00 WHERE id=1"      # updates in place
psql "DELETE FROM orders WHERE id=1"
```

The dashboard reflects each one without a refresh. Shipping an order removes it from
the result set even though the row still exists — the query defines what "open" means,
and Drasi tells you when something stops matching.

## Tidy up

```bash
docker rm -f drasi-demo-pg
```

## Next

- [Plugins](../../guides/plugins/) — pinning versions, verifying signatures, lockfiles.
- [Concepts](../../concepts/) — how sources, queries and reactions fit together.
