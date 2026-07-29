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

"""Tier 2a: locally built cdylib plugins.

These use plugins compiled from crates.io by `scripts/build_plugins.py`, so they
exercise the same loading path as the registry tests without depending on the
network at test time.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from drasi import Drasi, UnknownKindError

from .helpers import wait_for_at_least_rows, wait_for_query_running

pytestmark = pytest.mark.plugins

COUNTER_QUERY = "MATCH (c:Counter) RETURN c.value AS value"
MOCK_CONFIG: dict[str, Any] = {"dataType": {"type": "counter"}, "intervalMs": 50}


@pytest.fixture(scope="session")
def plugin_dir() -> Path:
    directory = Path(__file__).resolve().parents[2] / "plugins"
    binaries = [path for path in directory.glob("*") if path.suffix in {".so", ".dylib", ".dll"}]
    if not binaries:
        pytest.skip("run `python scripts/build_plugins.py` to build the test plugins")
    return directory


async def test_discovers_and_loads_every_plugin(engine: Drasi, plugin_dir: Path) -> None:
    summary = await engine.load_plugins(str(plugin_dir))

    assert summary["plugins"] >= 2
    kinds = await engine.plugin_kinds()
    assert "mock" in kinds["sources"]
    assert "log" in kinds["reactions"]


async def test_a_cdylib_source_feeds_a_continuous_query(engine: Drasi, plugin_dir: Path) -> None:
    await engine.load_plugins(str(plugin_dir))
    await engine.start()

    await engine.add_source("mock", "counters", MOCK_CONFIG)
    await engine.add_query("counts", COUNTER_QUERY, ["counters"])
    await wait_for_query_running(engine, "counts")

    rows = await wait_for_at_least_rows(engine, "counts", count=10)
    assert all(isinstance(row["value"], int) for row in rows)


async def test_a_python_reaction_observes_a_cdylib_source(engine: Drasi, plugin_dir: Path) -> None:
    """The two component models have to interoperate."""
    from .helpers import collect_events

    await engine.load_plugins(str(plugin_dir))
    await engine.add_source("mock", "counters", MOCK_CONFIG)
    await engine.add_query("counts", COUNTER_QUERY, ["counters"])
    events = await collect_events(engine, "watch", ["counts"])
    await engine.start()

    diffs = await events.take(1)
    assert diffs[0]["type"] in {"ADD", "UPDATE"}


async def test_a_cdylib_reaction_can_be_attached(engine: Drasi, plugin_dir: Path) -> None:
    await engine.load_plugins(str(plugin_dir))
    await engine.start()

    await engine.add_source("mock", "counters", MOCK_CONFIG)
    await engine.add_query("counts", COUNTER_QUERY, ["counters"])
    await engine.add_reaction("log", "logger", ["counts"], {})

    assert "logger" in [reaction_id for reaction_id, _ in await engine.list_reactions()]


async def test_config_schemas_are_exposed(engine: Drasi, plugin_dir: Path) -> None:
    await engine.load_plugins(str(plugin_dir))

    source_schema = await engine.source_config_schema("mock")
    assert "mock" in source_schema["name"].lower()
    assert isinstance(source_schema["schema"], dict)

    reaction_schema = await engine.reaction_config_schema("log")
    assert isinstance(reaction_schema["schema"], dict)


async def test_unknown_kinds_report_actionable_errors(engine: Drasi) -> None:
    with pytest.raises(UnknownKindError) as caught:
        await engine.add_source("postgres", "db", {})
    assert caught.value.code == "UNKNOWN_SOURCE_KIND"
    # The message should tell the caller how to fix it.
    assert "install_plugin" in str(caught.value)

    with pytest.raises(UnknownKindError) as caught:
        await engine.add_reaction("http", "webhook", ["q"], {})
    assert caught.value.code == "UNKNOWN_REACTION_KIND"


async def test_config_schema_for_an_unloaded_kind_is_rejected(engine: Drasi) -> None:
    with pytest.raises(UnknownKindError):
        await engine.source_config_schema("mock")


async def test_loading_an_empty_directory_is_not_an_error(engine: Drasi, tmp_path: Path) -> None:
    summary = await engine.load_plugins(str(tmp_path))
    assert summary == {
        "plugins": 0,
        "sources": 0,
        "reactions": 0,
        "bootstrap": 0,
        "secret_stores": 0,
        "identity_providers": 0,
        "skipped": 0,
    }


async def test_loading_a_missing_directory_reports_clearly(engine: Drasi, tmp_path: Path) -> None:
    from drasi import PluginNotFoundError

    with pytest.raises(PluginNotFoundError):
        await engine.load_plugins(str(tmp_path / "does-not-exist"))


async def test_plugins_from_two_directories_accumulate(
    engine: Drasi, plugin_dir: Path, tmp_path: Path
) -> None:
    sources = [path for path in plugin_dir.glob("*source*") if path.is_file()]
    reactions = [path for path in plugin_dir.glob("*reaction*") if path.is_file()]

    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    for path in sources:
        shutil.copy2(path, first / path.name)
    for path in reactions:
        shutil.copy2(path, second / path.name)

    await engine.load_plugins(str(first))
    assert (await engine.plugin_kinds())["sources"] == ["mock"]

    await engine.load_plugins(str(second))
    kinds = await engine.plugin_kinds()
    assert kinds["sources"] == ["mock"]
    assert kinds["reactions"] == ["log"]


async def test_a_plugin_type_that_does_not_exist_yet_is_still_discovered(
    engine: Drasi, plugin_dir: Path, tmp_path: Path
) -> None:
    """Discovery matches the `drasi_` prefix, not a list of plugin types.

    Enumerating types is what went wrong: the host SDK's defaults name source,
    reaction and bootstrap, so secret store and identity plugins were skipped
    without a word, and a type added later would go the same way. The plugin SDK
    already defines an index backend descriptor with no loader collection, so
    "later" is not hypothetical.

    A real plugin binary under a type name that does not exist stands in for
    that future type; it loads, while a library outside the naming convention
    does not and is counted.
    """
    source = next(path for path in plugin_dir.glob("libdrasi_source_*"))
    suffix = source.suffix
    shutil.copy(source, tmp_path / f"libdrasi_indexbackend_future{suffix}")
    shutil.copy(source, tmp_path / f"libdrasi_secret-store_legacy{suffix}")
    shutil.copy(source, tmp_path / f"libunrelated_thing{suffix}")

    summary = await engine.load_plugins(tmp_path)

    # The future type and the older hyphenated spelling both load; the library
    # that does not follow the convention is reported rather than ignored.
    assert summary["plugins"] == 2, summary
    assert summary["skipped"] == 1, summary
