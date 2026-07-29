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

"""Checks the built site for internal links that go nowhere.

`tests/unit/test_docs.py` checks links written in the Markdown. This checks the
HTML Hugo actually produced, which also covers links the theme generates - menus,
breadcrumbs, pagination, "edit this page" - and catches a page that fails to
render at the path something links to.

Run it after a build:

    cd website && hugo --gc --minify
    python scripts/check_site_links.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "website" / "public"

# The site is served from a project subpath, so absolute internal links start here.
PREFIX = "/drasi-python/"

# Hugo emits these without a corresponding file in every build.
IGNORED_SUFFIXES = (".xml", ".json", ".ico", ".png", ".svg", ".jpg", ".webmanifest")

LINK = re.compile(r'(?:href|src)=(?:"([^"]+)"|\'([^\']+)\'|([^\s>"\']+))')


def _targets(html: str) -> set[str]:
    found: set[str] = set()
    for quoted, single, bare in LINK.findall(html):
        found.add(quoted or single or bare)
    return found


def _is_internal(target: str) -> bool:
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc:
        return False
    return target.startswith(PREFIX)


def _exists(target: str) -> bool:
    path = unquote(urlparse(target).path)
    relative = path.removeprefix(PREFIX).strip("/")
    candidate = PUBLIC / relative if relative else PUBLIC
    return candidate.is_file() or (candidate / "index.html").is_file()


def main() -> int:
    if not PUBLIC.is_dir():
        print(
            f"{PUBLIC.relative_to(ROOT)} does not exist. Build the site first:\n"
            "  cd website && hugo --gc --minify",
            file=sys.stderr,
        )
        return 1

    pages = sorted(PUBLIC.rglob("*.html"))
    broken: dict[str, set[str]] = {}
    for page in pages:
        html = page.read_text(encoding="utf-8", errors="ignore")
        for target in _targets(html):
            if not _is_internal(target) or target.endswith(IGNORED_SUFFIXES):
                continue
            if not _exists(target):
                broken.setdefault(target, set()).add(str(page.relative_to(PUBLIC)))

    if broken:
        print(f"{len(broken)} broken internal link(s):", file=sys.stderr)
        for target, sources in sorted(broken.items()):
            print(f"  {target}", file=sys.stderr)
            for source in sorted(sources)[:3]:
                print(f"      from {source}", file=sys.stderr)
        return 1

    print(f"checked {len(pages)} page(s); no broken internal links")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
