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

"""The same engine, without await.

`drasi.sync` runs the event loop for you on a background thread, which is what
you want in a script or a notebook. In an application that already has a loop,
use `drasi.Drasi` and await it instead.

    python examples/sync_quickstart.py
"""

import os

# The engine logs at INFO by default, which drowns out an example's own output.
os.environ.setdefault("RUST_LOG", "warn")

from drasi.sync import Drasi  # noqa: E402

OPEN_ORDERS = "MATCH (o:Order) WHERE o.status = 'open' RETURN o.id AS id, o.total AS total"


def main() -> None:
    with Drasi.create("sync-demo") as drasi:
        drasi.start()
        drasi.add_python_source("orders")
        drasi.add_query("open", OPEN_ORDERS, ["orders"])
        drasi.wait_for_query("open")

        # A stream is an ordinary iterator here, not an async one.
        results = drasi.query_results("open")

        for order_id, total in [("o1", 42), ("o2", 17)]:
            drasi.push_change(
                "orders",
                {
                    "op": "insert",
                    "id": order_id,
                    "labels": ["Order"],
                    "properties": {"id": order_id, "status": "open", "total": total},
                },
            )

        print("changes as they arrive:")
        seen = 0
        for event in results:
            for diff in event["results"]:
                print(f"  {diff['type']} {diff['data']}")
                seen += 1
            if seen >= 2:
                break

        print(f"\nopen orders: {drasi.get_query_results('open')}")


if __name__ == "__main__":
    main()
