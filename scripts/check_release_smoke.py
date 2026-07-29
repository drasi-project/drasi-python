#!/usr/bin/env python3
"""Replay the release workflow's wheel smoke test against the current checkout.

The release workflow copies a subset of the repository into a scratch tree and
runs the test suite there against the *installed wheel*. Any test that reads a
repository path outside that subset passes in CI and then fails during the
release -- after the tag is cut. That is exactly how v0.1.3 broke: the docs
tests read ``website/`` and ``.github/``, neither of which is copied.

This script makes that assumption executable on every CI run. Both the file
list and the pytest selector are parsed out of ``release.yml`` rather than
restated here, so the guard cannot drift away from the workflow it guards.
"""

from __future__ import annotations

import ast
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


def _step(name: str) -> str:
    """Return the raw YAML text of a named workflow step."""
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.find(f"- name: {name}")
    if start == -1:
        raise SystemExit(f"{WORKFLOW}: no step named {name!r}")
    following = text.find("\n      - name: ", start + 1)
    return text[start:] if following == -1 else text[start:following]


def copy_list() -> list[str]:
    """The paths the release workflow copies into its smoke tree."""
    block = _step("Prepare smoke-test tree")
    match = re.search(r"for name in (\[.*?\]):", block, re.DOTALL)
    if match is None:
        raise SystemExit("could not find the smoke tree's copy list in release.yml")
    names = ast.literal_eval(re.sub(r"\n\s*", " ", match.group(1)))
    if not names:
        raise SystemExit("the smoke tree's copy list is empty")
    return list(names)


def selector() -> str:
    """The ``-m`` marker expression the release workflow's smoke test uses."""
    block = _step("Smoke-test installed wheel")
    match = re.search(r"pytest\"? -m \"([^\"]+)\"", block)
    if match is None:
        raise SystemExit("could not find the smoke test's pytest selector in release.yml")
    return match.group(1)


def main() -> int:
    names = copy_list()
    marker = selector()
    print(f"smoke tree copies: {', '.join(names)}")
    print(f"smoke selector:    -m {marker!r}")

    with tempfile.TemporaryDirectory() as scratch:
        smoke = Path(scratch) / "wheel-smoke"
        smoke.mkdir()
        for name in names:
            source = ROOT / name
            if source.is_dir():
                shutil.copytree(
                    source,
                    smoke / name,
                    ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"),
                )
            elif source.exists():
                shutil.copy2(source, smoke / name)

        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-m", marker, "-q", "-p", "no:cacheprovider"],
            cwd=smoke,
        )

    if result.returncode != 0:
        print(
            "\nThe release smoke test would fail.\n"
            "A test read a repository path the smoke tree does not contain.\n"
            "Either mark it so the smoke selector excludes it, or add the path\n"
            "to the copy list in .github/workflows/release.yml.",
            file=sys.stderr,
        )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
