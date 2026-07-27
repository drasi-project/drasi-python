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

"""The type stubs must describe what the extension actually exposes.

Stubs are hand-written, so nothing but a test stops them drifting away from the
Rust module as methods are added or renamed.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import drasi

ROOT = Path(__file__).resolve().parents[2]
STUB = ROOT / "python" / "drasi" / "_drasi.pyi"

# Defined by PyO3 rather than declared in the stub's class body.
DUNDER_ALLOWLIST = {"__aenter__", "__aexit__"}


@pytest.fixture(scope="module")
def stub() -> ast.Module:
    return ast.parse(STUB.read_text(encoding="utf-8"))


def _class(stub: ast.Module, name: str) -> ast.ClassDef:
    for node in stub.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is missing from {STUB.name}")


def _top_level_names(stub: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in stub.body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef):
            names.add(node.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def test_stub_declares_every_engine_method(stub: ast.Module) -> None:
    declared = {
        node.name for node in _class(stub, "Drasi").body if isinstance(node, ast.FunctionDef)
    } - DUNDER_ALLOWLIST
    # `id` is a property in the stub, so it is an AnnAssign rather than a def.
    declared.add("id")

    actual = {name for name in dir(drasi.Drasi) if not name.startswith("_")}

    assert not actual - declared, "the stub is missing engine methods"
    assert not declared - actual, "the stub declares methods the extension lacks"


def test_stub_declares_everything_the_package_exports(stub: ast.Module) -> None:
    missing = set(drasi.__all__) - _top_level_names(stub)
    assert not missing, f"the stub is missing {sorted(missing)}"


def test_py_typed_marker_is_present() -> None:
    assert (ROOT / "python" / "drasi" / "py.typed").exists()


def test_exception_hierarchy_is_rooted_at_drasi_error() -> None:
    for name in drasi.__all__:
        attribute = getattr(drasi, name)
        if isinstance(attribute, type) and issubclass(attribute, BaseException):
            assert issubclass(attribute, drasi.DrasiError), name


def test_every_error_code_is_unique_and_upper_snake_case() -> None:
    codes = drasi.ERROR_CODES
    assert len(codes) == len(set(codes))
    for code in codes:
        assert code.replace("_", "").isalnum() and code.isupper(), code
