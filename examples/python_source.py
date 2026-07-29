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

"""Push changes from your own code and react to the results.

Needs no plugins, no network and no database.

    python examples/python_source.py
"""

import os

# The engine logs at INFO by default, which drowns out an example's own output.
# Set RUST_LOG=info (or debug) to see what the engine is doing.
os.environ.setdefault("RUST_LOG", "warn")

import asyncio

from drasi import Drasi
from drasi.types import QueryResultEvent  # noqa: E402

OPEN_ORDERS = """
MATCH (o:Order)
WHERE o.status = 'open'
RETURN o.id AS id, o.customer AS customer, o.total AS total
"""


async def main() -> None:
    async with await Drasi.create("orders-app") as drasi:
        # Start first, then add components: they auto-start individually.
        await drasi.start()

        await drasi.add_python_source("orders")
        await drasi.add_query("open-orders", OPEN_ORDERS, ["orders"])

        def on_change(event: QueryResultEvent) -> None:
            for diff in event["results"]:
                # Which of `data`, `before` and `after` a diff carries is decided by
                # its `type`, which a single TypedDict cannot express, so these reads
                # are checked at runtime rather than by the type checker.
                if diff["type"] == "ADD":
                    print(f"  + {diff['data']}")
                elif diff["type"] == "DELETE":
                    print(f"  - {diff['data']}")
                else:
                    print(f"  ~ {diff['before']} -> {diff['after']}")

        await drasi.add_python_reaction("printer", ["open-orders"], on_change)

        print("placing two orders")
        for order_id, customer, total in [("o1", "Ada", 42), ("o2", "Grace", 17)]:
            await drasi.push_change(
                "orders",
                {
                    "op": "insert",
                    "id": order_id,
                    "labels": ["Order"],
                    # The change `id` is the graph key; a query selecting `o.id`
                    # reads a property, so emit it too.
                    "properties": {
                        "id": order_id,
                        "customer": customer,
                        "status": "open",
                        "total": total,
                    },
                },
            )
        await asyncio.sleep(0.3)

        print("shipping o1 — it should leave the result set")
        await drasi.push_change(
            "orders",
            {
                "op": "update",
                "id": "o1",
                "labels": ["Order"],
                "properties": {
                    "id": "o1",
                    "customer": "Ada",
                    "status": "shipped",
                    "total": 42,
                },
            },
        )
        await asyncio.sleep(0.3)

        print("\nstill open:", await drasi.get_query_results("open-orders"))


if __name__ == "__main__":
    asyncio.run(main())
