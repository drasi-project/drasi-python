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

import pytest

import drasi

pytestmark = pytest.mark.docs

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


def test_every_error_code_is_actually_raised() -> None:
    """A code nothing constructs can never be caught.

    `test_every_documented_error_code_exists` only ties the guide to
    `ERROR_CODES`, so a variant declared in the enum and documented in the guide
    satisfies both while being unreachable. Three were: two named cases that
    raised something else, and one raised nowhere at all.
    """
    source = ROOT / "src"
    errors_rs = (source / "errors.rs").read_text(encoding="utf-8")
    enum = errors_rs.split("pub enum DrasiErrorCode {", 1)[1].split("\n}", 1)[0]
    variants = re.findall(r"^\s{4}(\w+),$", enum, re.M)
    assert variants, "no error code variants found in errors.rs"

    raised = "\n".join(
        path.read_text(encoding="utf-8")
        for path in source.rglob("*.rs")
        if path.name != "errors.rs"
    )
    unreachable = [v for v in set(variants) if f"DrasiErrorCode::{v}" not in raised]
    assert not unreachable, (
        "error codes that nothing raises, so nobody can catch them: "
        + ", ".join(sorted(unreachable))
    )


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


def _hugo_build_settings(workflow: str) -> dict[str, str]:
    """Pulls the settings both site builds have to agree on."""
    text = (ROOT / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
    hugo = re.search(r"HUGO_VERSION:\s*(\S+)", text)
    node = re.search(r'node-version:\s*"?([\d.]+)"?', text)
    action = re.search(r"uses:\s*(peaceiris/actions-hugo@\S+)", text)
    assert hugo and node and action, f"{workflow} no longer pins the site build"
    return {"hugo": hugo.group(1), "node": node.group(1), "action": action.group(1)}


def test_both_workflows_build_the_site_the_same_way() -> None:
    """CI builds the site and the deploy workflow publishes it.

    Two copies of the same build is the price of making the site a check
    everywhere rather than only when `website/` changes. They are only useful
    if they agree, and a version that drifts would mean CI passing on a build
    that is not the one being published.
    """
    assert _hugo_build_settings("ci.yml") == _hugo_build_settings("website.yml")


def test_the_link_checker_matches_the_published_base_path() -> None:
    """A wrong prefix would make every internal link look external, and pass."""
    checker = (ROOT / "scripts" / "check_site_links.py").read_text(encoding="utf-8")
    prefix = re.search(r'PREFIX = "([^"]+)"', checker)
    assert prefix and prefix.group(1) == "/drasi-python/"


def _python_blocks() -> list[tuple[str, str]]:
    import textwrap

    blocks: list[tuple[str, str]] = []
    for page in sorted(CONTENT.rglob("*.md")):
        text = page.read_text(encoding="utf-8")
        for index, match in enumerate(re.finditer(r"```python\n(.*?)```", text, re.S)):
            source = textwrap.dedent(match.group(1))
            if source.lstrip().startswith(">>>"):
                continue
            blocks.append((f"{page.relative_to(CONTENT)}#{index}", source))
    return blocks


def test_every_python_sample_parses() -> None:
    """Catches a sample nobody can run at all.

    A `...` placeholder inside a dict literal is a syntax error rather than the
    elision it looks like, and reading the page will not tell you.
    """
    import ast
    import textwrap

    blocks = _python_blocks()
    assert blocks, "no python samples found"

    broken: list[str] = []
    for name, source in blocks:
        try:
            ast.parse(source)
        except SyntaxError:
            # Fragments use a bare `await`, which needs a function around it.
            try:
                ast.parse("async def _f():\n" + textwrap.indent(source, "    "))
            except SyntaxError as err:
                broken.append(f"{name}: {err}")
    assert not broken, "samples that do not parse:\n  " + "\n  ".join(broken)


def test_samples_only_call_methods_that_exist() -> None:
    """Catches an invented method or keyword argument.

    Most of these samples cannot be executed - they are fragments - so the call
    itself is the only thing left to check.
    """
    import ast
    import textwrap

    from drasi import Drasi

    problems: list[str] = []
    for name, source in _python_blocks():
        try:
            tree = ast.parse(source)
        except SyntaxError:
            tree = ast.parse("async def _f():\n" + textwrap.indent(source, "    "))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            base = node.func.value
            receiver = getattr(base, "id", None) or getattr(getattr(base, "func", None), "id", None)
            if receiver not in {"drasi", "Drasi", "engine"}:
                continue
            method = getattr(Drasi, node.func.attr, None)
            if method is None:
                problems.append(f"{name}: Drasi has no {node.func.attr!r}")
                continue
            signature = getattr(method, "__text_signature__", None)
            if not signature:
                continue
            accepted = {
                part.split("=")[0].strip().lstrip("*")
                for part in signature.strip("()").split(",")
                if part.strip() not in {"", "*", "/", "$self"}
            }
            for keyword in node.keywords:
                if keyword.arg and keyword.arg not in accepted:
                    problems.append(
                        f"{name}: {node.func.attr}() has no {keyword.arg!r}; "
                        f"accepts {sorted(accepted)}"
                    )
    assert not problems, "samples calling something that does not exist:\n  " + "\n  ".join(
        problems
    )
