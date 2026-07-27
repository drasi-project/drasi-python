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

"""The README quickstart must actually run.

Documentation examples rot silently. This one is short, needs no plugins and no
network, so there is no reason not to execute it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

README = Path(__file__).resolve().parents[2] / "README.md"


def _quickstart() -> str:
    match = re.search(
        r"```python\n(import asyncio\nfrom drasi import Drasi\n.*?)```", README.read_text(), re.S
    )
    assert match, "the README no longer contains the quickstart example"
    return match.group(1)


def test_readme_quickstart_runs(capsys: pytest.CaptureFixture[str]) -> None:
    # The snippet calls asyncio.run itself, so it must not run inside a loop.
    exec(compile(_quickstart(), "README.md", "exec"), {"__name__": "__main__"})

    output = capsys.readouterr().out
    assert "ADD {'id': 'o1', 'total': 42}" in output
    assert "[{'id': 'o1', 'total': 42}]" in output


def test_readme_uses_single_quoted_cypher_literals() -> None:
    """Drasi's parser rejects double-quoted string literals."""
    assert "o.status = 'open'" in README.read_text()
