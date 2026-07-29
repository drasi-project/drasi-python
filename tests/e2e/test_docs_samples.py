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

"""The code in the documentation has to run.

Reviewing samples by reading them is how a sample that raises `NameError` on the
first line ships: both blocking-API samples referred to a constant that was
never defined, and neither reading them nor type checking them noticed. Running
them does.
"""

from __future__ import annotations

import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONTENT = ROOT / "website" / "content"

# Samples that reach a real database, a registry or a dashboard port belong to
# the tiers that provide those, not here.
NEEDS_THE_WORLD = ("install_plugin", "postgres", "localhost")


def _samples() -> list[tuple[str, str]]:
    """Every self-contained program in the docs, as (id, source)."""
    found: list[tuple[str, str]] = []
    for page in sorted(CONTENT.rglob("*.md")):
        text = page.read_text(encoding="utf-8")
        for index, match in enumerate(re.finditer(r"```python\n(.*?)```", text, re.S)):
            source = textwrap.dedent(match.group(1))
            if source.lstrip().startswith(">>>"):
                continue
            self_contained = "import " in source and (
                "asyncio.run(" in source or "with Drasi.create" in source
            )
            if not self_contained:
                continue
            if any(needle in source for needle in NEEDS_THE_WORLD):
                continue
            found.append((f"{page.relative_to(CONTENT)}#{index}", source))
    return found


SAMPLES = _samples()


def test_there_are_samples_to_run() -> None:
    """Guards the extractor: a test that silently runs nothing proves nothing."""
    assert SAMPLES, "no runnable samples found in website/content"


@pytest.mark.parametrize("name,source", SAMPLES, ids=[name for name, _ in SAMPLES])
def test_documented_sample_runs(name: str, source: str, tmp_path: Path) -> None:
    script = tmp_path / "sample.py"
    script.write_text(source, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=tmp_path,
        env={"RUST_LOG": "error", "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, (
        f"{name} failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


@pytest.mark.parametrize("name,source", SAMPLES, ids=[name for name, _ in SAMPLES])
def test_documented_sample_produces_output(name: str, source: str, tmp_path: Path) -> None:
    """A sample that prints nothing has nothing to show a reader."""
    if "print(" not in source:
        pytest.skip("sample does not print")

    script = tmp_path / "sample.py"
    script.write_text(source, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=tmp_path,
        env={"RUST_LOG": "error", "PATH": "/usr/bin:/bin"},
    )
    assert result.stdout.strip(), f"{name} printed nothing"
    # An empty result set usually means the sample raced its own query.
    assert "[]" not in result.stdout, f"{name} printed an empty result set:\n{result.stdout}"
    assert "None" not in result.stdout, (
        f"{name} printed None, which usually means a property the query selects "
        f"was never set:\n{result.stdout}"
    )
