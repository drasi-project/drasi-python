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

"""Crash recovery for a durable Python source with only a redb WAL."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
WORKER = Path(__file__).with_name("wal_recovery_worker.py")


def run_worker(mode: str, wal_path: Path) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [sys.executable, str(WORKER), mode, str(wal_path)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=45,
        )
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(
            f"{mode} timed out\nstdout:\n{exc.stdout or ''}\nstderr:\n{exc.stderr or ''}"
        ) from exc

    assert result.returncode == 0, (
        f"{mode} exited {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    try:
        result_line = result.stdout.rstrip().splitlines()[-1]
        return json.loads(result_line)
    except (IndexError, json.JSONDecodeError) as exc:
        raise AssertionError(
            f"{mode} did not emit exact JSON\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        ) from exc


def test_durable_python_source_replays_after_a_fresh_process(tmp_path: Path) -> None:
    wal_path = tmp_path / "wal"

    assert run_worker("writer", wal_path) == {
        "mode": "writer",
        "rows": [{"id": "o1"}],
    }
    assert wal_path.is_dir()
    assert (wal_path / "orders.redb").is_file()

    assert run_worker("reader", wal_path) == {
        "mode": "reader",
        "rows": [{"id": "o1"}],
    }
