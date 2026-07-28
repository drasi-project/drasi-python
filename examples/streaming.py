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

"""Watch a query change, without polling.

Three different things can be streamed, and they are easy to confuse:

  * results  — the diffs a query produces
  * events   — lifecycle transitions of a component
  * logs     — log lines, including from plugins

    python examples/streaming.py
"""

import os

# The engine logs at INFO by default, which drowns out an example's own output.
# Set RUST_LOG=info (or debug) to see what the engine is doing.
os.environ.setdefault("RUST_LOG", "warn")

import asyncio  # noqa: E402

from drasi import Drasi  # noqa: E402
from drasi.types import SourceChange

OPEN_ORDERS = """
MATCH (o:Order)
WHERE o.status = 'open'
RETURN o.id AS id, o.total AS total
"""


def order(order_id: str, status: str, total: int) -> SourceChange:
    return {
        "op": "insert" if status == "open" else "update",
        "id": order_id,
        "labels": ["Order"],
        # The change `id` is the graph key; a query selecting `o.id` reads a
        # property, so emit it too.
        "properties": {"id": order_id, "status": status, "total": total},
    }


async def place_orders(drasi: Drasi) -> None:
    """Drives the query from the side, so the stream has something to show."""
    await asyncio.sleep(0.2)
    await drasi.push_change("orders", order("o1", "open", 42))
    await drasi.push_change("orders", order("o2", "open", 17))
    await asyncio.sleep(0.2)
    # Shipping o1 does not delete it, but it no longer matches the query.
    await drasi.push_change("orders", order("o1", "shipped", 42))


async def main() -> None:
    async with await Drasi.create("streaming-demo") as drasi:
        await drasi.start()
        await drasi.add_python_source("orders")
        await drasi.add_query("open-orders", OPEN_ORDERS, ["orders"])
        await drasi.wait_for_query("open-orders")

        results = await drasi.query_results("open-orders")
        asyncio.create_task(place_orders(drasi))

        print("watching for changes to the open orders...\n")
        seen = 0
        async for event in results:
            for diff in event["results"]:
                if diff["type"] == "ADD":
                    print(f"  + {diff['data']}")
                elif diff["type"] == "DELETE":
                    print(f"  - {diff['data']}  (no longer open)")
                else:
                    print(f"  ~ {diff['before']} -> {diff['after']}")
                seen += 1
            if seen >= 3:
                break

        # Lifecycle events are a separate stream, and replay their history.
        print("\nhow the query got here:")
        events = await drasi.query_events("open-orders")
        for _ in range(3):
            event = await anext(aiter(events))
            print(f"  {event['status']}: {event.get('message') or ''}".rstrip())

        print(f"\nstill open: {await drasi.get_query_results('open-orders')}")


if __name__ == "__main__":
    asyncio.run(main())
