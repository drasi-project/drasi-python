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

"""Fresh-process worker for the Python-source WAL recovery acceptance test."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from drasi import Drasi

QUERY = "MATCH (o:Order) RETURN o.id AS id"
EXPECTED_ROWS = [{"id": "o1"}]


async def wait_for_rows(drasi: Drasi) -> list[dict[str, Any]]:
    async def poll() -> list[dict[str, Any]]:
        while True:
            rows = await drasi.get_query_results("q")
            if rows == EXPECTED_ROWS:
                return rows
            await asyncio.sleep(0.02)

    return await asyncio.wait_for(poll(), timeout=15)


async def writer(wal_path: Path) -> dict[str, object]:
    drasi = await Drasi.create("wal-recovery", wal_provider={"path": str(wal_path)})
    try:
        await drasi.start()
        await drasi.add_python_source("orders", durability=True)
        await drasi.add_query("q", QUERY, ["orders"])
        await drasi.wait_for_query("q", timeout=15)
        await drasi.push_change(
            "orders",
            {
                "op": "insert",
                "id": "o1",
                "labels": ["Order"],
                "properties": {"id": "o1"},
            },
        )
        return {"mode": "writer", "rows": await wait_for_rows(drasi)}
    finally:
        await drasi.close()


async def reader(wal_path: Path) -> dict[str, object]:
    drasi = await Drasi.from_config({"id": "wal-recovery", "wal_provider": {"path": str(wal_path)}})
    try:
        await drasi.add_python_source("orders", durability=True)
        await drasi.add_query("q", QUERY, ["orders"])
        await drasi.wait_for_query("q", timeout=15)
        return {"mode": "reader", "rows": await wait_for_rows(drasi)}
    finally:
        await drasi.close()


async def main() -> None:
    mode, raw_path = sys.argv[1:]
    action = {"writer": writer, "reader": reader}[mode]
    print(json.dumps(await action(Path(raw_path)), sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    asyncio.run(main())
