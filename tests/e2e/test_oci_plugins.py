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

"""Tier 2b/2c: download and install real plugins from ghcr.io.

These tests exercise the requirement that the plugin ecosystem actually works:
search the registry, resolve the build that is compatible with *this* host,
download it, verify it, install it, load it and run a query through it.

`source/mock` is used because it needs no external services, so the full cycle
runs on every platform. Set `DRASI_OCI_TESTS=1` to enable them locally.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from drasi import Drasi, PluginCompatibilityError, PluginSignatureError, host_info

from .helpers import wait_for_query_running, wait_for_rows

pytestmark = pytest.mark.oci

MOCK_SOURCE = "source/mock"
LOG_REACTION = "reaction/log"
COUNTER_QUERY = "MATCH (c:Counter) RETURN c.value AS value"
MOCK_CONFIG: dict[str, Any] = {"dataType": {"type": "counter"}, "intervalMs": 50}


# ------------------------------------------------------------------ discovery


async def test_registry_index_lists_published_plugins(engine: Drasi) -> None:
    plugins = await engine.search_plugins()
    references = {plugin["reference"] for plugin in plugins}

    assert MOCK_SOURCE in references
    assert any(reference.startswith("source/") for reference in references)
    assert any(reference.startswith("reaction/") for reference in references)
    assert any(reference.startswith("bootstrap/") for reference in references)


async def test_plugin_tags_are_published_per_platform(engine: Drasi) -> None:
    tags = await engine.list_plugin_tags(MOCK_SOURCE)
    assert tags, "expected published tags for source/mock"

    suffix = host_info()["target_triple"]
    assert suffix, "host must report a target triple"
    # Plugins are per-platform rather than multi-arch, so at least one tag must
    # carry an architecture suffix.
    assert any("-" in tag for tag in tags)


# ------------------------------------------------------------------ resolution


async def test_resolution_picks_a_build_matching_this_host(engine: Drasi) -> None:
    host = host_info()
    resolved = await engine.resolve_plugin(MOCK_SOURCE)

    assert resolved["kind"] == "mock"
    assert resolved["plugin_type"] == "source"
    # The whole point of resolution: the artifact must match this machine.
    assert resolved["target_triple"] == host["target_triple"]
    for field in ("sdk_version", "core_version", "lib_version"):
        assert _major_minor(resolved[field]) == _major_minor(host[field]), field


async def test_resolution_of_an_unpublished_plugin_fails_clearly(engine: Drasi) -> None:
    with pytest.raises(PluginCompatibilityError) as caught:
        await engine.resolve_plugin("source/definitely-not-a-real-plugin")
    # The message must say what this host is, or the failure is unactionable.
    assert "this host is" in str(caught.value)
    assert caught.value.code == "PLUGIN_INCOMPATIBLE"


# --------------------------------------------------------------------- install


async def test_install_downloads_loads_and_runs_a_plugin(engine: Drasi, tmp_path: Path) -> None:
    """The headline test: registry to query results in one call."""
    installed = await engine.install_plugin(MOCK_SOURCE, directory=tmp_path)

    assert installed["loaded"] is True
    assert Path(installed["path"]).exists()
    assert Path(installed["path"]).parent == tmp_path
    assert (await engine.plugin_kinds())["sources"] == ["mock"]

    await engine.start()
    await engine.add_source("mock", "counters", MOCK_CONFIG)
    await engine.add_query("counts", COUNTER_QUERY, ["counters"])
    await wait_for_query_running(engine, "counts")

    rows = await wait_for_rows(engine, "counts", count=10)
    assert all("value" in row for row in rows)


async def test_installed_plugin_exposes_its_config_schema(engine: Drasi, tmp_path: Path) -> None:
    await engine.install_plugin(MOCK_SOURCE, directory=tmp_path)
    schema = await engine.source_config_schema("mock")

    assert "mock" in schema["name"].lower()
    assert isinstance(schema["schema"], dict)


async def test_install_names_the_file_so_the_loader_finds_it(engine: Drasi, tmp_path: Path) -> None:
    installed = await engine.install_plugin(MOCK_SOURCE, directory=tmp_path)
    name = Path(installed["path"]).name

    # The loader discovers plugins by filename pattern, so the prefix and
    # extension have to match the host's conventions.
    assert "drasi_source_mock" in name
    assert name.endswith((".so", ".dylib", ".dll"))


async def test_a_reaction_plugin_can_be_installed(engine: Drasi, tmp_path: Path) -> None:
    await engine.install_plugin(LOG_REACTION, directory=tmp_path)
    assert (await engine.plugin_kinds())["reactions"] == ["log"]


async def test_install_without_loading_leaves_the_registry_empty(
    engine: Drasi, tmp_path: Path
) -> None:
    installed = await engine.install_plugin(MOCK_SOURCE, directory=tmp_path, load=False)

    assert installed["loaded"] is False
    assert Path(installed["path"]).exists()
    assert (await engine.plugin_kinds())["sources"] == []


async def test_a_downloaded_plugin_can_be_loaded_from_a_directory(
    engine: Drasi, tmp_path: Path
) -> None:
    await engine.install_plugin(MOCK_SOURCE, directory=tmp_path, load=False)

    summary = await engine.load_plugins(str(tmp_path))
    assert summary["plugins"] == 1
    assert summary["sources"] == 1
    assert (await engine.plugin_kinds())["sources"] == ["mock"]


# ---------------------------------------------------------------- verification


async def test_verification_reports_a_signature_status(engine: Drasi, tmp_path: Path) -> None:
    installed = await engine.install_plugin(MOCK_SOURCE, directory=tmp_path, verify=True)
    # A genuine artifact must never come back as tampered.
    assert installed["verification"] in {"verified", "unsigned"}


# ----------------------------------------------------------- compatibility 2c


async def test_a_wrong_architecture_build_is_rejected(engine: Drasi, tmp_path: Path) -> None:
    """Pinning a tag for another platform must fail rather than load garbage."""
    host_suffix = _arch_suffix(host_info()["target_triple"])
    tags = await engine.list_plugin_tags(MOCK_SOURCE)
    foreign = [
        tag for tag in tags if "-" in tag and not tag.endswith(host_suffix) and "dev" not in tag
    ]
    if not foreign:
        pytest.skip("no foreign-architecture tags published to test against")

    with pytest.raises(PluginCompatibilityError):
        await engine.install_plugin(
            f"ghcr.io/drasi-project/source/mock:{foreign[0]}", directory=tmp_path
        )


async def test_requiring_a_signature_rejects_an_unsigned_artifact(
    engine: Drasi, tmp_path: Path
) -> None:
    try:
        installed = await engine.install_plugin(
            MOCK_SOURCE, directory=tmp_path, verify=True, load=False
        )
    except PluginSignatureError as err:
        assert err.code == "PLUGIN_SIGNATURE_INVALID"
        return

    if installed["verification"] == "verified":
        pytest.skip("published artifacts are signed and verifiable from this host")

    with pytest.raises(PluginSignatureError) as caught:
        await engine.install_plugin(MOCK_SOURCE, directory=tmp_path, require_signed=True)
    assert caught.value.code == "PLUGIN_SIGNATURE_INVALID"


async def test_a_corrupted_plugin_is_not_loaded(engine: Drasi, tmp_path: Path) -> None:
    installed = await engine.install_plugin(MOCK_SOURCE, directory=tmp_path, load=False)
    binary = Path(installed["path"])
    binary.write_bytes(b"this is not a shared library")

    summary = await engine.load_plugins(str(tmp_path))
    assert summary["sources"] == 0
    assert (await engine.plugin_kinds())["sources"] == []


async def test_hash_verification_is_an_allowlist(engine: Drasi, tmp_path: Path) -> None:
    installed = await engine.install_plugin(MOCK_SOURCE, directory=tmp_path, load=False)
    name = Path(installed["path"]).name

    # A wrong hash must skip the file rather than load it anyway.
    summary = await engine.load_plugins(str(tmp_path), {name: "00" * 32})
    assert summary["sources"] == 0

    correct = _sha256(Path(installed["path"]))
    summary = await engine.load_plugins(str(tmp_path), {name: correct})
    assert summary["sources"] == 1


async def test_a_file_absent_from_the_hash_map_is_skipped(engine: Drasi, tmp_path: Path) -> None:
    installed = await engine.install_plugin(MOCK_SOURCE, directory=tmp_path, load=False)
    other = tmp_path / "extra"
    other.mkdir()
    shutil.copy2(installed["path"], other / Path(installed["path"]).name)

    summary = await engine.load_plugins(str(other), {"some-other-file.so": "00" * 32})
    assert summary["sources"] == 0


# --------------------------------------------------------------------- helpers


def _major_minor(version: str) -> tuple[str, str]:
    parts = version.split(".")
    return parts[0], parts[1]


def _arch_suffix(target_triple: str) -> str:
    mapping = {
        "x86_64-unknown-linux-gnu": "linux-amd64",
        "aarch64-unknown-linux-gnu": "linux-arm64",
        "x86_64-apple-darwin": "darwin-amd64",
        "aarch64-apple-darwin": "darwin-arm64",
        "x86_64-pc-windows-msvc": "windows-msvc-amd64",
    }
    return mapping.get(target_triple, target_triple)


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()
