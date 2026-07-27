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

"""Offline tests for the registry pin-drift guard."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "check_registry_pins", ROOT / "scripts" / "check_registry_pins.py"
)
assert _spec is not None and _spec.loader is not None
pins_module = importlib.util.module_from_spec(_spec)
sys.modules["check_registry_pins"] = pins_module
_spec.loader.exec_module(pins_module)


def test_reads_exact_pins_from_cargo_toml() -> None:
    pins = pins_module.cargo_pins(ROOT / "Cargo.toml")
    assert pins == {
        "drasi-core": "0.5.7",
        "drasi-lib": "0.8.9",
        "drasi-plugin-sdk": "0.10.0",
    }


def test_rejects_a_non_exact_pin(tmp_path: Path) -> None:
    cargo = tmp_path / "Cargo.toml"
    cargo.write_text(
        'drasi-core = "=0.5.7"\ndrasi-lib = "0.8.9"\ndrasi-plugin-sdk = "=0.10.0"\n',
        encoding="utf-8",
    )
    with pytest.raises(pins_module.RegistryError, match="drasi-lib is not pinned"):
        pins_module.cargo_pins(cargo)


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        (["0.2.6-darwin-arm64", "0.2.7-darwin-arm64"], "0.2.7-darwin-arm64"),
        # Plain numeric ordering must not put 0.2.10 below 0.2.9.
        (["0.2.9-linux-amd64", "0.2.10-linux-amd64"], "0.2.10-linux-amd64"),
        # Un-suffixed and pre-release tags are ignored.
        (["0.2.7", "0.2.8-dev.1-linux-amd64", "0.2.7-linux-amd64"], "0.2.7-linux-amd64"),
        # Longest arch suffix wins when stripping the version.
        (["0.3.0-linux-musl-amd64", "0.2.0-linux-amd64"], "0.3.0-linux-musl-amd64"),
    ],
)
def test_picks_the_newest_released_tag(tags: list[str], expected: str) -> None:
    assert pins_module.latest_release_tag(tags) == expected


def test_errors_when_no_released_tags_exist() -> None:
    with pytest.raises(pins_module.RegistryError, match="no released"):
        pins_module.latest_release_tag(["latest", "0.1.0-dev.1-linux-amd64"])


def test_compatibility_is_major_minor_only() -> None:
    assert pins_module.major_minor("0.8.9") == pins_module.major_minor("0.8.20")
    assert pins_module.major_minor("0.8.9") != pins_module.major_minor("0.9.0")
