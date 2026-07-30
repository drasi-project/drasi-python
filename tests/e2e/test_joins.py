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

"""Synthetic joins: relating nodes that no source relates.

Two sources that know nothing about each other have no relationship between
their nodes, so a query cannot traverse from one to the other. A join declares
one, matching on a property value, and it is maintained incrementally.

`joins` was exposed and typed but exercised by nothing, so these tests pin the
behaviour rather than the signature.
"""

from __future__ import annotations

import asyncio
from typing import Any

from drasi import Drasi
from drasi.types import Join, SourceChange

from .helpers import wait_for_query_running, wait_for_rows

# The relationship type in the pattern is the join's `id`; it exists only
# because the join declares it.
ACROSS_SOURCES = """
MATCH (o:Order)-[:PLACED_BY]->(c:Customer)
RETURN o.id AS order_id, c.name AS customer
"""

PLACED_BY: list[Join] = [
    {
        "id": "PLACED_BY",
        "keys": [
            {"label": "Order", "property": "customer_email"},
            {"label": "Customer", "property": "email"},
        ],
    }
]


def customer(email: str) -> SourceChange:
    return {
        "op": "insert",
        "id": "c1",
        "labels": ["Customer"],
        "properties": {"id": "c1", "name": "Ada", "email": email},
    }


def order(email: str) -> SourceChange:
    return {
        "op": "insert",
        "id": "o1",
        "labels": ["Order"],
        "properties": {"id": "o1", "customer_email": email},
    }


async def _push(engine: Drasi, joins: list[Join] | None, order_email: str) -> None:
    await engine.start()
    await engine.add_python_source("orders")
    await engine.add_python_source("customers")
    await engine.add_query("q", ACROSS_SOURCES, ["orders", "customers"], joins=joins)
    await wait_for_query_running(engine, "q")

    await engine.push_change("customers", customer("ada@example.com"))
    await engine.push_change("orders", order(order_email))


async def _stays_empty(engine: Drasi) -> list[dict[str, Any]]:
    """Waiting for a row that should not arrive, and reporting that it did not.

    Reading the result set straight away would pass before the engine had a
    chance to produce anything, so this gives it the same window the positive
    case needs to converge.
    """
    await asyncio.sleep(1.5)
    return await engine.get_query_results("q")


async def test_a_join_relates_nodes_from_two_sources(engine: Drasi) -> None:
    await _push(engine, PLACED_BY, "ada@example.com")
    assert await wait_for_rows(engine, "q") == [{"order_id": "o1", "customer": "Ada"}]


async def test_without_the_join_the_pattern_matches_nothing(engine: Drasi) -> None:
    """The control: the relationship exists only because the join declares it."""
    await _push(engine, None, "ada@example.com")
    assert await _stays_empty(engine) == []


async def test_a_join_only_relates_nodes_whose_values_match(engine: Drasi) -> None:
    """Guards against a join that relates everything regardless of value."""
    await _push(engine, PLACED_BY, "someone@else.com")
    assert await _stays_empty(engine) == []
