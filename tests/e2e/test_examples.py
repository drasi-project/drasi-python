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

"""The examples must run, and the guide must describe the ones that exist.

An example that no longer works is worse than no example, and this is the first
thing anyone runs against a package that is not on PyPI yet.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"
GUIDE = EXAMPLES / "README.md"


def example_files() -> list[Path]:
    return sorted(EXAMPLES.glob("*.py"))


def run_example(name: str, timeout: int = 300) -> str:
    result = subprocess.run(
        [sys.executable, str(EXAMPLES / name)],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=ROOT,
    )
    assert result.returncode == 0, (
        f"{name} exited {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return result.stdout


def test_the_guide_documents_every_example() -> None:
    guide = GUIDE.read_text(encoding="utf-8")
    for example in example_files():
        assert example.name in guide, f"{example.name} is not mentioned in examples/README.md"


def test_the_guide_does_not_document_examples_that_were_removed() -> None:
    guide = GUIDE.read_text(encoding="utf-8")
    referenced = {
        line.split("`")[1]
        for line in guide.splitlines()
        if line.count("`") >= 2 and ".py" in line.split("`")[1]
    }
    existing = {example.name for example in example_files()}
    assert referenced <= existing, f"the guide references missing examples: {referenced - existing}"


def test_the_guide_does_not_promise_a_pypi_install() -> None:
    """The package is not released yet; `pip install drasi-lib` would just fail."""
    guide = GUIDE.read_text(encoding="utf-8").lower()
    assert "not published to pypi yet" in guide


def test_python_source_example_runs() -> None:
    output = run_example("python_source.py")
    assert "+ {'customer': 'Ada', 'id': 'o1', 'total': 42}" in output
    assert "- {'customer': 'Ada', 'id': 'o1', 'total': 42}" in output
    assert "still open: [{'customer': 'Grace', 'id': 'o2', 'total': 17}]" in output


def test_examples_are_quiet_by_default() -> None:
    """Engine logging at INFO buries an example's own output."""
    output = run_example("python_source.py")
    assert "INFO drasi_lib" not in output


@pytest.mark.oci
def test_install_plugin_example_runs() -> None:
    output = run_example("install_plugin.py")
    assert "plugins published" in output
    assert "resolves to" in output
    assert "counter rows:" in output


@pytest.mark.oci
@pytest.mark.docker
def test_postgres_example_runs() -> None:
    docker = pytest.importorskip("docker", reason="this example needs Docker")
    try:
        docker.from_env().ping()
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Docker is not available: {exc}")
    pytest.importorskip("psycopg", reason="this example needs psycopg")

    output = run_example("postgres_cdc.py")
    assert "+ {'customer': 'Ada', 'id': 1}" in output
    assert "- {'customer': 'Ada', 'id': 1}" in output
    assert "still open: []" in output
