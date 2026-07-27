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

"""Browse the plugin registry, then install and use a plugin.

`install_plugin` resolves the build that is compatible with this machine, so you
never have to work out which architecture tag you need.

    python examples/install_plugin.py
"""

import asyncio

from drasi import Drasi, host_info


async def main() -> None:
    info = host_info()
    print(f"host: {info['target_triple']}")
    print(f"  drasi-core {info['core_version']}, drasi-lib {info['lib_version']}")
    print(f"  plugin sdk {info['sdk_version']}, ffi abi {info['ffi_sdk_version']}\n")

    async with await Drasi.create("plugin-demo") as drasi:
        available = await drasi.search_plugins()
        sources = sorted(p["kind"] for p in available if p["plugin_type"] == "source")
        print(f"{len(available)} plugins published; sources include:")
        print("  " + ", ".join(sources[:12]) + " ...\n")

        # Resolve without downloading, to see what would be chosen.
        resolved = await drasi.resolve_plugin("source/mock")
        print(f"source/mock resolves to {resolved['version']} for {resolved['target_triple']}")

        installed = await drasi.install_plugin("source/mock", verify=True)
        print(f"installed to {installed['path']}")
        print(f"signature: {installed['verification']}\n")

        await drasi.start()
        await drasi.add_source(
            "mock",
            "counters",
            # Configuration keys are the plugin's own, so they keep its spelling.
            {"dataType": {"type": "counter"}, "intervalMs": 200},
        )
        await drasi.add_query("counts", "MATCH (c:Counter) RETURN c.value AS value", ["counters"])

        # A query finishes starting in the background, so wait for it before
        # reading results.
        await drasi.wait_for_query("counts")

        for _ in range(50):
            rows = await drasi.get_query_results("counts")
            if rows:
                print(f"counter rows: {rows[:5]}")
                break
            await asyncio.sleep(0.1)
        else:
            print("no rows arrived")


if __name__ == "__main__":
    asyncio.run(main())
