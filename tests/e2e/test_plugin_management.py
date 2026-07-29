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

"""Plugin watching, explicit pulls and lockfiles."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from drasi import Drasi, DrasiError, PluginNotFoundError

MOCK_SOURCE = "source/mock"


def built_plugins() -> Path:
    directory = Path(__file__).resolve().parents[2] / "plugins"
    if not any(directory.glob("*drasi_source_mock*")):
        pytest.skip("run `python scripts/build_plugins.py` first")
    return directory


# --------------------------------------------------------------------- watching


@pytest.mark.plugins
async def test_a_plugin_copied_into_a_watched_directory_is_loaded(
    engine: Drasi, tmp_path: Path
) -> None:
    await engine.watch_plugins(str(tmp_path), debounce_seconds=0.1)
    assert (await engine.plugin_kinds())["sources"] == []

    source = next(iter(built_plugins().glob("*drasi_source_mock*")))
    shutil.copy2(source, tmp_path / source.name)

    loop = asyncio.get_running_loop()
    deadline = loop.time() + 20.0
    while loop.time() < deadline:
        if "mock" in (await engine.plugin_kinds())["sources"]:
            return
        await asyncio.sleep(0.1)
    raise AssertionError("the watched plugin was never loaded")


async def test_watching_a_missing_directory_is_reported(engine: Drasi, tmp_path: Path) -> None:
    with pytest.raises(DrasiError):
        await engine.watch_plugins(str(tmp_path / "nope"))


# ----------------------------------------------------------------------- pulls


@pytest.mark.oci
async def test_pull_downloads_an_exact_reference(engine: Drasi, tmp_path: Path) -> None:
    resolved = await engine.resolve_plugin(MOCK_SOURCE)

    result = await engine.pull_plugin(
        resolved["reference"], str(tmp_path), "libdrasi_source_mock.dylib"
    )

    assert Path(result["path"]).exists()
    assert result["reference"] == resolved["reference"]
    # Pulling does not load, so nothing is registered.
    assert (await engine.plugin_kinds())["sources"] == []


@pytest.mark.oci
async def test_pulling_a_nonexistent_reference_fails(engine: Drasi, tmp_path: Path) -> None:
    with pytest.raises(PluginNotFoundError):
        await engine.pull_plugin(
            "ghcr.io/drasi-project/source/mock:0.0.0-does-not-exist",
            str(tmp_path),
            "plugin.so",
        )


# ------------------------------------------------------------------- lockfiles


@pytest.mark.oci
async def test_installs_can_be_pinned_and_replayed(engine: Drasi, tmp_path: Path) -> None:
    installed = await engine.install_plugin(MOCK_SOURCE, directory=tmp_path, load=False)

    count = await engine.write_lockfile(str(tmp_path))
    assert count == 1
    assert (tmp_path / "plugins.lock").exists()

    [pinned] = Drasi.read_lockfile(str(tmp_path))
    assert pinned["reference"] == installed["reference"]
    assert pinned["digest"].startswith("sha256:")
    assert pinned["file_hash"]
    assert pinned["version"] == installed["version"]


@pytest.mark.oci
async def test_a_lockfile_reinstalls_the_same_artifact(engine: Drasi, tmp_path: Path) -> None:
    await engine.install_plugin(MOCK_SOURCE, directory=tmp_path, load=False)
    await engine.write_lockfile(str(tmp_path))

    async with await Drasi.create("t-from-lock") as replayed:
        references = await replayed.install_from_lockfile(str(tmp_path))
        assert len(references) == 1
        assert (await replayed.plugin_kinds())["sources"] == ["mock"]


@pytest.mark.oci
async def test_a_lockfile_detects_a_tampered_binary(engine: Drasi, tmp_path: Path) -> None:
    """A pinned hash is what makes a lockfile worth having."""
    installed = await engine.install_plugin(MOCK_SOURCE, directory=tmp_path, load=False)
    await engine.write_lockfile(str(tmp_path))

    lockfile = (tmp_path / "plugins.lock").read_text()
    recorded_hash = Drasi.read_lockfile(str(tmp_path))[0]["file_hash"]
    assert recorded_hash is not None, "the lockfile should record a hash to corrupt"
    corrupted = lockfile.replace(recorded_hash, "00" * 32)
    (tmp_path / "plugins.lock").write_text(corrupted)

    async with await Drasi.create("t-tampered") as replayed:
        with pytest.raises(DrasiError) as caught:
            await replayed.install_from_lockfile(str(tmp_path))
        assert caught.value.code == "PLUGIN_SIGNATURE_INVALID"
    assert Path(installed["path"]).exists()


async def test_writing_a_lockfile_with_nothing_installed_is_rejected(
    engine: Drasi, tmp_path: Path
) -> None:
    with pytest.raises(DrasiError):
        await engine.write_lockfile(str(tmp_path))


async def test_reading_a_missing_lockfile_is_reported(tmp_path: Path) -> None:
    with pytest.raises(PluginNotFoundError):
        Drasi.read_lockfile(str(tmp_path))


# -------------------------------------------------------------- query tuning


async def test_a_query_can_be_registered_without_auto_starting(engine: Drasi) -> None:
    await engine.start()
    await engine.add_python_source("s")
    await engine.add_query("manual", "MATCH (o:Order) RETURN o.id AS id", ["s"], auto_start=False)

    assert await engine.get_query_status("manual") != "Running"

    await engine.start_query("manual")
    await engine.wait_for_query("manual")
    assert await engine.get_query_status("manual") == "Running"


async def test_tuning_options_are_accepted(engine: Drasi) -> None:
    await engine.start()
    await engine.add_python_source("s")
    await engine.add_query(
        "tuned",
        "MATCH (o:Order) RETURN o.id AS id",
        ["s"],
        enable_bootstrap=False,
        bootstrap_timeout_seconds=5,
        priority_queue_capacity=64,
        dispatch_buffer_capacity=64,
        outbox_capacity=64,
        dispatch_mode="channel",
    )
    await engine.wait_for_query("tuned")

    await engine.push_change(
        "s", {"op": "insert", "id": "o1", "labels": ["Order"], "properties": {"id": "o1"}}
    )
    from .helpers import wait_for_rows

    assert await wait_for_rows(engine, "tuned") == [{"id": "o1"}]


async def test_an_unknown_dispatch_mode_is_rejected(engine: Drasi) -> None:
    await engine.start()
    await engine.add_python_source("s")
    with pytest.raises(DrasiError) as caught:
        await engine.add_query(
            "bad",
            "MATCH (o:Order) RETURN o.id AS id",
            ["s"],
            dispatch_mode="carrier-pigeon",  # pyright: ignore[reportArgumentType]  # invalid on purpose
        )
    assert caught.value.code == "CONFIG_INVALID"


async def test_a_shared_library_the_scan_ignores_is_counted(engine: Drasi, tmp_path: Path) -> None:
    """A skipped file used to leave no trace at all.

    The host SDK matches plugins by filename, and anything matching no pattern
    is passed over in silence. That is how secret store and identity plugins
    went missing: a directory holding three of them reported one, and nothing
    said the other two had been ignored. The count makes it visible.
    """
    (tmp_path / "libsomething_else.dylib").write_bytes(b"not a plugin")
    (tmp_path / "notes.txt").write_text("not a library either", encoding="utf-8")

    summary = await engine.load_plugins(tmp_path)

    assert summary["plugins"] == 0
    assert summary["skipped"] == 1, "the unmatched shared library should be reported"


async def test_an_empty_directory_skips_nothing(engine: Drasi, tmp_path: Path) -> None:
    summary = await engine.load_plugins(tmp_path)
    assert summary["skipped"] == 0
