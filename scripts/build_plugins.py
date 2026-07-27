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

"""Build the cdylib plugins used by the tier 2a end-to-end tests.

The plugin crates are fetched from crates.io and built with the
``dynamic-plugin`` feature, which is what exports the ``drasi_plugin_init``
symbol the host loader looks for.

The versions here are not arbitrary: a plugin must be built against the same
``drasi-plugin-sdk`` this host uses, or it will be rejected at load time. See
``docs/plugins.md``.

Usage::

    python scripts/build_plugins.py [--release] [--out plugins]
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USER_AGENT = "drasi-python-plugin-builder"

# (crate, version, cargo lib name)
PLUGINS = [
    ("drasi-source-mock", "0.2.7", "drasi_source_mock"),
    ("drasi-reaction-log", "0.2.5", "drasi_reaction_log"),
]


def library_name(lib: str) -> str:
    if sys.platform == "win32":
        return f"{lib}.dll"
    if sys.platform == "darwin":
        return f"lib{lib}.dylib"
    return f"lib{lib}.so"


def fetch(crate: str, version: str, into: Path) -> Path:
    """Downloads and extracts a crate tarball, returning its source directory."""
    source_dir = into / f"{crate}-{version}"
    if (source_dir / "Cargo.toml").exists():
        return source_dir

    into.mkdir(parents=True, exist_ok=True)
    archive = into / f"{crate}-{version}.crate"
    url = f"https://static.crates.io/crates/{crate}/{crate}-{version}.crate"
    print(f"  fetching {url}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        archive.write_bytes(response.read())

    with tarfile.open(archive, "r:gz") as tar:
        # `filter="data"` refuses absolute paths and links that escape the
        # destination, which matters for archives we did not create.
        try:
            tar.extractall(into, filter="data")
        except TypeError:  # pragma: no cover - Python < 3.12
            tar.extractall(into)
    archive.unlink()
    return source_dir


def build(source_dir: Path, target_dir: Path, release: bool) -> Path:
    command = ["cargo", "build", "--features", "dynamic-plugin"]
    if release:
        command.append("--release")

    environment = dict(os.environ)
    # A shared target directory lets the two plugins reuse each other's
    # compiled dependencies, which is most of the build time.
    environment["CARGO_TARGET_DIR"] = str(target_dir)
    subprocess.run(command, cwd=source_dir, check=True, env=environment)
    return target_dir / ("release" if release else "debug")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", action="store_true", help="build optimised plugins")
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "plugins",
        help="directory to place the built plugins in (default: ./plugins)",
    )
    args = parser.parse_args()

    if shutil.which("cargo") is None:
        print("error: cargo is required to build the test plugins", file=sys.stderr)
        return 2

    work = ROOT / "target" / "plugin-src"
    shared_target = ROOT / "target" / "plugin-build"
    args.out.mkdir(parents=True, exist_ok=True)

    for crate, version, lib in PLUGINS:
        artifact = library_name(lib)
        destination = args.out / artifact
        if destination.exists():
            print(f"{crate} {version}: already built")
            continue

        print(f"{crate} {version}:")
        source_dir = fetch(crate, version, work)
        built = build(source_dir, shared_target, args.release) / artifact
        if not built.exists():
            print(f"error: expected {built} to exist after the build", file=sys.stderr)
            return 1
        shutil.copy2(built, destination)
        print(f"  -> {destination.relative_to(ROOT)}")

    print(f"\nPlugins are in {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
