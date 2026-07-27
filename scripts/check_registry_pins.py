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

"""Fail if our Drasi crate pins drift away from the published plugin registry.

A Drasi plugin is a native library loaded into this process. The host only
accepts a plugin whose ``sdk``/``core``/``lib`` versions match the host's on
``major.minor``. Those versions are baked into the plugin at publish time and
recorded as OCI annotations on the artifact.

So our ``Cargo.toml`` pins are not a free choice: bumping ``drasi-lib`` without a
matching plugin release would silently make every published plugin
uninstallable. This script compares our pins against what is actually published
and exits non-zero on drift.

Usage::

    python scripts/check_registry_pins.py [--reference source/mock]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

REGISTRY = "ghcr.io"
NAMESPACE = "drasi-project"
USER_AGENT = "drasi-python-registry-pin-check"

# Cargo.toml dependency name -> OCI annotation recording the version it was built against.
PINNED_CRATES = {
    "drasi-core": "io.drasi.plugin.core-version",
    "drasi-lib": "io.drasi.plugin.lib-version",
    "drasi-plugin-sdk": "io.drasi.plugin.sdk-version",
}

# Suffixes appearing on plugin tags, longest first so `linux-musl-amd64` wins over
# `linux-amd64` when stripping.
ARCH_SUFFIXES = (
    "linux-musl-amd64",
    "linux-musl-arm64",
    "windows-msvc-amd64",
    "linux-amd64",
    "linux-arm64",
    "windows-amd64",
    "windows-arm64",
    "darwin-amd64",
    "darwin-arm64",
)


class RegistryError(RuntimeError):
    """The registry could not be queried."""


def _get(url: str, token: str | None = None, accept: str | None = None) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    if accept:
        request.add_header("Accept", accept)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read()
    except urllib.error.URLError as exc:  # pragma: no cover - network failure path
        raise RegistryError(f"GET {url} failed: {exc}") from exc


def _token(repository: str) -> str:
    url = f"https://{REGISTRY}/token?scope=repository:{repository}:pull&service={REGISTRY}"
    payload = json.loads(_get(url))
    token = payload.get("token")
    if not token:
        raise RegistryError(f"no anonymous pull token for {repository}")
    return token


def list_tags(repository: str) -> list[str]:
    token = _token(repository)
    url = f"https://{REGISTRY}/v2/{repository}/tags/list?n=1000"
    return json.loads(_get(url, token=token)).get("tags") or []


def manifest_annotations(repository: str, tag: str) -> dict[str, str]:
    token = _token(repository)
    url = f"https://{REGISTRY}/v2/{repository}/manifests/{tag}"
    manifest = json.loads(
        _get(url, token=token, accept="application/vnd.oci.image.manifest.v1+json")
    )
    return manifest.get("annotations") or {}


def _version_key(tag: str) -> tuple[int, ...]:
    base = tag
    for suffix in ARCH_SUFFIXES:
        if base.endswith(f"-{suffix}"):
            base = base[: -len(suffix) - 1]
            break
    return tuple(int(part) for part in re.findall(r"\d+", base)) or (0,)


def latest_release_tag(tags: list[str]) -> str:
    """Newest tag that carries an arch suffix and is not a pre-release."""
    candidates = [
        tag
        for tag in tags
        if any(tag.endswith(f"-{suffix}") for suffix in ARCH_SUFFIXES)
        and "dev" not in tag
        and re.match(r"^\d+\.\d+\.\d+-", tag)
    ]
    if not candidates:
        raise RegistryError("no released, arch-suffixed tags found")
    return max(candidates, key=_version_key)


def cargo_pins(cargo_toml: Path) -> dict[str, str]:
    """Reads the exact (``=x.y.z``) version pins out of Cargo.toml."""
    text = cargo_toml.read_text(encoding="utf-8")
    pins: dict[str, str] = {}
    for crate in PINNED_CRATES:
        match = re.search(rf'^{re.escape(crate)}\s*=\s*.*?"=([0-9][^"]*)"', text, re.M)
        if not match:
            raise RegistryError(f"{crate} is not pinned with an exact `=x.y.z` version")
        pins[crate] = match.group(1)
    return pins


def major_minor(version: str) -> tuple[int, int]:
    parts = version.split(".")
    return int(parts[0]), int(parts[1])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reference",
        default="source/mock",
        help="plugin to compare against (default: source/mock)",
    )
    args = parser.parse_args()

    repository = f"{NAMESPACE}/{args.reference}"
    root = Path(__file__).resolve().parent.parent

    try:
        pins = cargo_pins(root / "Cargo.toml")
        tag = latest_release_tag(list_tags(repository))
        annotations = manifest_annotations(repository, tag)
    except RegistryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"comparing pins against {REGISTRY}/{repository}:{tag}\n")

    drift = False
    for crate, annotation in PINNED_CRATES.items():
        published = annotations.get(annotation)
        pinned = pins[crate]
        if published is None:
            print(f"  {crate:<18} pinned={pinned:<10} published=<missing annotation>  SKIP")
            continue
        ok = major_minor(published) == major_minor(pinned)
        drift = drift or not ok
        status = "ok" if ok else "DRIFT"
        print(f"  {crate:<18} pinned={pinned:<10} published={published:<10} {status}")

    if drift:
        print(
            "\nPins have drifted from the published plugins. Plugins built against the "
            "published versions will be rejected by this host.\n"
            "Either realign the pins in Cargo.toml or wait for a matching plugin release.",
            file=sys.stderr,
        )
        return 1

    print("\nPins are compatible with the published plugin registry.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
