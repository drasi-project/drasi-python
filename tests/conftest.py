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

"""Shared fixtures.

Every test gets its own engine, and the fixture always shuts it down — a leaked
engine keeps background tasks alive and makes later tests flaky or hangs
interpreter exit.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest

from drasi import Drasi


@pytest.fixture
async def engine(request: pytest.FixtureRequest) -> AsyncIterator[Drasi]:
    """A fresh, stopped engine named after the test using it."""
    instance = await Drasi.create(f"test-{request.node.name}"[:96])
    try:
        yield instance
    finally:
        await instance.close()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skips network- and Docker-dependent tiers unless they are opted into."""
    if os.environ.get("DRASI_OCI_TESTS"):
        return
    skip_oci = pytest.mark.skip(reason="set DRASI_OCI_TESTS=1 to run registry tests")
    for item in items:
        if "oci" in item.keywords:
            item.add_marker(skip_oci)
