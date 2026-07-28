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

"""Offline tests for the package version-drift guard."""

from __future__ import annotations

import importlib.util
import shutil
import sys
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "check_version_sync", ROOT / "scripts" / "check_version_sync.py"
)
assert _spec is not None and _spec.loader is not None
version_module = importlib.util.module_from_spec(_spec)
sys.modules["check_version_sync"] = version_module
_spec.loader.exec_module(version_module)


@contextmanager
def project_tree(name: str) -> Generator[Path]:
    root = ROOT / ".pytest-version-sync" / name
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    try:
        yield root
    finally:
        shutil.rmtree(root)


def write_project(root: Path, cargo_version: str, lock_version: str | None = None) -> None:
    (root / "Cargo.toml").write_text(
        f'[package]\nname = "drasi-python"\nversion = "{cargo_version}"\n',
        encoding="utf-8",
    )
    (root / "pyproject.toml").write_text(
        '[build-system]\nbuild-backend = "maturin"\n\n'
        '[project]\nname = "drasi-lib"\ndynamic = ["version"]\n',
        encoding="utf-8",
    )
    (root / "Cargo.lock").write_text(
        f'[[package]]\nname = "drasi-python"\nversion = "{lock_version or cargo_version}"\n',
        encoding="utf-8",
    )
    package = root / "python" / "drasi"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        "from ._drasi import __version__\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("pip install drasi-lib\n", encoding="utf-8")


def test_accepts_an_in_sync_project_tree() -> None:
    with project_tree("in-sync") as root:
        write_project(root, "0.1.0")

        version, problems = version_module.version_problems(root)

    assert version == "0.1.0"
    assert problems == []


def test_detects_lockfile_drift() -> None:
    with project_tree("lockfile-drift") as root:
        write_project(root, "0.1.0", lock_version="0.1.1")

        _, problems = version_module.version_problems(root)

    assert [problem.message for problem in problems] == [
        "lockfile package version is 0.1.1, expected 0.1.0"
    ]


def test_detects_pyproject_literal_version() -> None:
    with project_tree("pyproject-drift") as root:
        write_project(root, "0.1.0")
        (root / "pyproject.toml").write_text(
            '[project]\nname = "drasi-lib"\nversion = "0.2.0"\n',
            encoding="utf-8",
        )

        _, problems = version_module.version_problems(root)

    assert len(problems) == 1
    assert "pyproject.toml [project].version is 0.2.0" in problems[0].message


def test_detects_hardcoded_python_and_documentation_versions() -> None:
    with project_tree("hardcoded-drift") as root:
        write_project(root, "0.1.0")
        (root / "python" / "drasi" / "__init__.py").write_text(
            '__version__ = "0.0.9"\n',
            encoding="utf-8",
        )
        (root / "README.md").write_text(
            "pip install drasi-lib==0.0.8\n",
            encoding="utf-8",
        )

        _, problems = version_module.version_problems(root)

    assert sorted(problem.message for problem in problems) == [
        "hardcoded package version 0.0.8, expected 0.1.0",
        "hardcoded package version 0.0.9, expected 0.1.0",
    ]
