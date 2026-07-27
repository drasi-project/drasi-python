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

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"
GUIDE = EXAMPLES / "README.md"


def example_files() -> list[Path]:
    """The runnable examples, excluding underscore-prefixed support modules."""
    return sorted(p for p in EXAMPLES.glob("*.py") if not p.name.startswith("_"))


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


def test_the_guide_does_not_reference_files_that_were_removed() -> None:
    """Covers support modules as well as examples — anything the guide links to."""
    guide = GUIDE.read_text(encoding="utf-8")
    referenced = {
        line.split("`")[1]
        for line in guide.splitlines()
        if line.count("`") >= 2 and ".py" in line.split("`")[1]
    }
    missing = {name for name in referenced if not (EXAMPLES / name).exists()}
    assert not missing, f"examples/README.md references missing files: {sorted(missing)}"


def test_the_guide_does_not_promise_a_pypi_install() -> None:
    """The package is not released yet; `pip install drasi-lib` would just fail."""
    guide = GUIDE.read_text(encoding="utf-8").lower()
    assert "not published to pypi yet" in guide


def test_the_guide_only_invokes_tools_the_venv_actually_has() -> None:
    """`uv venv` does not install pip, so `.venv/bin/pip` is not a thing.

    Any `.venv/bin/<tool>` the guide tells you to *run* must exist after
    `make venv && make develop`. Only fenced shell blocks are checked, and the
    fallback block that builds the environment with `python -m venv` is excluded
    because that route does provide pip.
    """
    venv_bin = ROOT / ".venv" / "bin"
    if not venv_bin.is_dir():
        pytest.skip("run `make venv && make develop` first")

    guide = GUIDE.read_text(encoding="utf-8")
    # The <details> block documents the plain `python -m venv` route.
    main_path = re.sub(r"<details>.*?</details>", "", guide, flags=re.S)
    commands = "\n".join(re.findall(r"```bash\n(.*?)```", main_path, flags=re.S))

    invoked = set(re.findall(r"\.venv/bin/([A-Za-z0-9_.-]+)", commands))
    assert invoked, "expected the guide to show some .venv commands"
    missing = {tool for tool in invoked if not (venv_bin / tool).exists()}
    assert not missing, (
        f"examples/README.md tells you to run {sorted(missing)}, which `make venv` does not install"
    )


def test_the_guide_only_references_make_targets_that_exist() -> None:
    """Renaming a target should not silently invalidate the guide."""
    guide = GUIDE.read_text(encoding="utf-8")
    commands = "\n".join(re.findall(r"```bash\n(.*?)```", guide, flags=re.S))
    referenced = set(re.findall(r"\bmake ([a-z][a-z0-9-]*)", commands))
    assert referenced, "expected the guide to show some make commands"

    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    defined = set(re.findall(r"^([a-z][a-z0-9-]*):", makefile, flags=re.M))
    missing = referenced - defined
    assert not missing, f"examples/README.md references missing make targets: {sorted(missing)}"


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
