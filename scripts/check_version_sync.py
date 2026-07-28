#!/usr/bin/env python3
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

"""Fail if the Python package version drifts away from Cargo.toml.

Maturin publishes the ``drasi-lib`` Python distribution from this Rust crate.
The package version is intentionally owned by ``Cargo.toml``: ``pyproject.toml``
declares it as dynamic, and the extension exposes ``drasi.__version__`` from
``CARGO_PKG_VERSION``.

That only stays true while nobody adds a second source of truth. This script
checks that maturin will still derive the version from Cargo, that ``Cargo.lock``
records the same package version when present, and that common hardcoded Python
or documentation pins have not gone stale.

Usage::

    python scripts/check_version_sync.py
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    tomllib = None  # type: ignore[assignment]

SEMVER = r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?"
SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest-version-sync",
    ".pytest_cache",
    ".release-check",
    ".ruff_cache",
    ".venv",
    "dist",
    "target",
}
TEXT_SUFFIXES = {".md", ".py", ".pyi", ".toml", ".yaml", ".yml"}
SKIP_FILES = {Path("tests/unit/test_version_sync.py")}
SCAN_PATHS = ("README.md", "CHANGELOG.md", "docs", "python", ".github", "scripts")


class VersionSyncError(RuntimeError):
    """The package version could not be read or checked."""


@dataclass(frozen=True)
class VersionProblem:
    """A single version drift finding."""

    path: Path
    message: str


def _package_section(text: str) -> str:
    match = re.search(r"(?ms)^\[package\]\s*(.*?)(?=^\[|\Z)", text)
    if not match:
        raise VersionSyncError("Cargo.toml has no [package] section")
    return match.group(1)


def cargo_version(cargo_toml: Path) -> str:
    """Reads the package version out of Cargo.toml."""
    text = cargo_toml.read_text(encoding="utf-8")
    match = re.search(rf'(?m)^version\s*=\s*"({SEMVER})"\s*$', _package_section(text))
    if not match:
        raise VersionSyncError("Cargo.toml [package].version is missing or not semver")
    return match.group(1)


def _load_toml(path: Path) -> dict[str, object]:
    if tomllib is None:
        return _load_pyproject_fallback(path)
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _load_pyproject_fallback(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    project = re.search(r"(?ms)^\[project\]\s*(.*?)(?=^\[|\Z)", text)
    if not project:
        return {"project": {}}
    body = project.group(1)
    version = re.search(rf'(?m)^version\s*=\s*"({SEMVER})"\s*$', body)
    dynamic = re.search(r"(?m)^dynamic\s*=\s*\[(.*?)\]\s*$", body)
    values = re.findall(r'"([^"]+)"', dynamic.group(1)) if dynamic else []
    data: dict[str, object] = {"dynamic": values}
    if version:
        data["version"] = version.group(1)
    return {"project": data}


def maturin_version(pyproject_toml: Path, expected: str) -> str:
    """Confirms pyproject leaves the version dynamic for maturin."""
    data = _load_toml(pyproject_toml)
    project = data.get("project")
    if not isinstance(project, dict):
        raise VersionSyncError("pyproject.toml has no [project] table")

    literal = project.get("version")
    if literal is not None:
        if literal != expected:
            raise VersionSyncError(
                f"pyproject.toml [project].version is {literal}, expected {expected}"
            )
        raise VersionSyncError(
            "pyproject.toml sets [project].version; keep it dynamic so maturin uses Cargo.toml"
        )

    dynamic = project.get("dynamic")
    if not isinstance(dynamic, list) or "version" not in dynamic:
        raise VersionSyncError('pyproject.toml [project].dynamic must include "version"')

    return expected


def cargo_lock_version(cargo_lock: Path) -> str | None:
    """Reads this crate's package version out of Cargo.lock, if it is present."""
    if not cargo_lock.exists():
        return None
    text = cargo_lock.read_text(encoding="utf-8")
    match = re.search(
        rf'(?ms)^\[\[package\]\]\s*name\s*=\s*"drasi-python"\s*version\s*=\s*"({SEMVER})"',
        text,
    )
    if not match:
        raise VersionSyncError("Cargo.lock has no drasi-python package entry")
    return match.group(1)


def _is_skipped(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    if relative in SKIP_FILES:
        return True
    parts = relative.parts
    return any(part in SKIP_DIRS for part in parts)


def _text_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for scan_path in SCAN_PATHS:
        base = root / scan_path
        if not base.exists():
            continue
        candidates = base.rglob("*") if base.is_dir() else [base]
        for path in candidates:
            if path.is_dir() or _is_skipped(path, root) or path.suffix not in TEXT_SUFFIXES:
                continue
            files.append(path)
    return files


def hardcoded_version_problems(root: Path, expected: str) -> list[VersionProblem]:
    """Finds common second sources of truth for the Python package version."""
    problems: list[VersionProblem] = []
    version_patterns = [
        re.compile(rf'__version__\s*=\s*["\']({SEMVER})["\']'),
        re.compile(rf"\bdrasi-lib\s*(?:==|===|~=)\s*({SEMVER})\b"),
    ]

    for path in _text_files(root):
        if path.name in {"Cargo.toml", "Cargo.lock", "pyproject.toml"}:
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in version_patterns:
            for match in pattern.finditer(text):
                found = match.group(1)
                if found != expected:
                    problems.append(
                        VersionProblem(
                            path=path,
                            message=f"hardcoded package version {found}, expected {expected}",
                        )
                    )
    return problems


def version_problems(root: Path) -> tuple[str, list[VersionProblem]]:
    """Checks every known package-version source against Cargo.toml."""
    expected = cargo_version(root / "Cargo.toml")
    problems: list[VersionProblem] = []

    try:
        produced = maturin_version(root / "pyproject.toml", expected)
    except VersionSyncError as exc:
        problems.append(VersionProblem(root / "pyproject.toml", str(exc)))
    else:
        if produced != expected:
            problems.append(
                VersionProblem(
                    root / "pyproject.toml",
                    f"maturin would produce {produced}, expected {expected}",
                )
            )

    try:
        locked = cargo_lock_version(root / "Cargo.lock")
    except VersionSyncError as exc:
        problems.append(VersionProblem(root / "Cargo.lock", str(exc)))
    else:
        if locked is not None and locked != expected:
            problems.append(
                VersionProblem(
                    root / "Cargo.lock",
                    f"lockfile package version is {locked}, expected {expected}",
                )
            )

    problems.extend(hardcoded_version_problems(root, expected))
    return expected, problems


def main() -> int:
    root = Path(__file__).resolve().parent.parent

    try:
        expected, problems = version_problems(root)
    except VersionSyncError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if problems:
        print(f"Package version drift detected; Cargo.toml says {expected}.\n", file=sys.stderr)
        for problem in problems:
            print(f"  {problem.path.relative_to(root)}: {problem.message}", file=sys.stderr)
        return 1

    print(f"Package version is in sync at {expected}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
