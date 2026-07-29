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

"""The documentation site must describe the package that actually exists.

Published docs that quietly fall behind the code are worse than no docs, because
a reader has no way to tell which parts are still true.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import drasi

ROOT = Path(__file__).resolve().parents[2]
WEBSITE = ROOT / "website"
CONTENT = WEBSITE / "content"
API_PAGE = CONTENT / "docs" / "api" / "_index.md"


def test_the_api_reference_matches_the_stubs() -> None:
    """The page claims to be generated, so it has to be regenerable."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_api_reference.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_every_documented_error_code_exists() -> None:
    """The error-handling guide tabulates codes; none may be invented or stale."""
    guide = (CONTENT / "docs" / "guides" / "error-handling.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"^\| `([A-Z][A-Z0-9_]+)` \|", guide, re.M))
    assert documented, "no error codes found in the guide"
    assert documented == set(drasi.ERROR_CODES)


def test_documented_recovery_policies_match_the_type() -> None:
    guide = (CONTENT / "docs" / "guides" / "python-reactions.md").read_text(encoding="utf-8")
    section = guide.split("| Policy | Behaviour |")[1].split("\n\n")[0]
    documented = set(re.findall(r"^\| `(\w+)` \|", section, re.M))
    assert documented == {"strict", "auto_reset", "skip_gap"}


def test_internal_links_point_at_pages_that_exist() -> None:
    """A relative link in Hugo resolves against the section, not the repository."""
    pages = {path for path in CONTENT.rglob("*.md")}
    missing: list[str] = []
    for page in pages:
        # Hugo serves `guides/streaming.md` at `/docs/guides/streaming/`, so a
        # relative link resolves against the page as though it were a directory.
        section = page.parent if page.name == "_index.md" else page.parent / page.stem
        for target in re.findall(r"\]\((?!https?://|#)([^)]+)\)", page.read_text(encoding="utf-8")):
            target = target.split("#")[0]
            if not target:
                continue
            resolved = (section / target).resolve()
            candidates = [
                resolved.with_suffix(".md"),
                resolved / "_index.md",
                Path(str(resolved).rstrip("/") + ".md"),
            ]
            if not any(candidate.exists() for candidate in candidates):
                missing.append(f"{page.relative_to(CONTENT)} -> {target}")
    assert not missing, "links to pages that do not exist:\n  " + "\n  ".join(sorted(missing))


def test_the_site_declares_the_right_repository() -> None:
    config = (WEBSITE / "config.toml").read_text(encoding="utf-8")
    assert "drasi-project.github.io/drasi-python/" in config
    assert "drasi-nodejs" not in config, "config still points at the Node.js repository"
