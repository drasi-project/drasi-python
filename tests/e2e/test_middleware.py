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

"""Query middleware: transforming changes on their way into a query.

Middleware is declared per query and applied per source, so a declaration only
does anything where a source's `pipeline` names it. These tests assert the
transformation actually happens rather than that the argument is accepted --
before this was wired up, passing `middleware` was silently ignored.
"""

from __future__ import annotations

import pytest

from drasi import Drasi, DrasiError
from drasi.types import Middleware

from .helpers import wait_for_query_running, wait_for_rows

# `city` is nested under `address`, so the query only resolves it if middleware
# has promoted it to a top-level property first.
CITY_QUERY = "MATCH (o:Order) RETURN o.id AS id, o.city AS city"

PROMOTE_CITY: list[Middleware] = [
    {
        "name": "flatten",
        "kind": "promote",
        "config": {"mappings": [{"path": "$.address.city", "target_name": "city"}]},
    }
]

ORDER = {
    "op": "insert",
    "id": "o1",
    "labels": ["Order"],
    "properties": {"id": "o1", "address": {"city": "Cambridge"}},
}


async def test_middleware_transforms_a_change_before_the_query_sees_it(engine: Drasi) -> None:
    await engine.start()
    await engine.add_python_source("orders")
    await engine.add_query(
        "q",
        CITY_QUERY,
        [{"id": "orders", "pipeline": ["flatten"]}],
        middleware=PROMOTE_CITY,
    )
    await wait_for_query_running(engine, "q")

    await engine.push_change("orders", ORDER)

    assert await wait_for_rows(engine, "q") == [{"id": "o1", "city": "Cambridge"}]


async def test_without_the_pipeline_the_same_change_is_untransformed(engine: Drasi) -> None:
    """The control: middleware declared but never referenced does nothing.

    This is what makes the test above meaningful -- it shows the promotion comes
    from the pipeline rather than from anything the source or query does.
    """
    await engine.start()
    await engine.add_python_source("orders")
    await engine.add_query("q", CITY_QUERY, ["orders"], middleware=PROMOTE_CITY)
    await wait_for_query_running(engine, "q")

    await engine.push_change("orders", ORDER)

    assert await wait_for_rows(engine, "q") == [{"id": "o1", "city": None}]


async def test_a_source_can_be_named_as_a_mapping_without_a_pipeline(engine: Drasi) -> None:
    """`{"id": ...}` and a bare string have to mean the same thing."""
    await engine.start()
    await engine.add_python_source("orders")
    await engine.add_query("q", CITY_QUERY, [{"id": "orders"}])
    await wait_for_query_running(engine, "q")

    await engine.push_change("orders", ORDER)

    assert await wait_for_rows(engine, "q") == [{"id": "o1", "city": None}]


async def test_an_unknown_middleware_kind_is_rejected(engine: Drasi) -> None:
    await engine.start()
    await engine.add_python_source("orders")

    with pytest.raises(DrasiError) as caught:
        await engine.add_query(
            "q",
            CITY_QUERY,
            [{"id": "orders", "pipeline": ["flatten"]}],
            middleware=[{"name": "flatten", "kind": "no-such-middleware", "config": {}}],
        )

    assert "no-such-middleware" in str(caught.value)


async def test_a_pipeline_naming_undeclared_middleware_is_rejected(engine: Drasi) -> None:
    await engine.start()
    await engine.add_python_source("orders")

    with pytest.raises(DrasiError) as caught:
        await engine.add_query(
            "q",
            CITY_QUERY,
            [{"id": "orders", "pipeline": ["never-declared"]}],
            middleware=PROMOTE_CITY,
        )

    assert "never-declared" in str(caught.value)


async def test_middleware_needs_a_name_and_a_kind(engine: Drasi) -> None:
    await engine.start()
    await engine.add_python_source("orders")

    with pytest.raises(DrasiError) as missing_kind:
        await engine.add_query("q", CITY_QUERY, ["orders"], middleware=[{"name": "flatten"}])
    assert "kind" in str(missing_kind.value)

    with pytest.raises(DrasiError) as missing_name:
        await engine.add_query("q", CITY_QUERY, ["orders"], middleware=[{"kind": "promote"}])
    assert "name" in str(missing_name.value)


async def test_a_malformed_source_entry_is_rejected(engine: Drasi) -> None:
    await engine.start()
    await engine.add_python_source("orders")

    with pytest.raises(DrasiError):
        await engine.add_query("q", CITY_QUERY, [{"pipeline": ["flatten"]}])


async def test_from_config_reads_middleware() -> None:
    """`from_config` has to reach the same parser, not a parallel path.

    It previously read only five keys per query, so a middleware block in a
    declarative topology was dropped without complaint. A malformed declaration
    is the cheapest proof the key is now read: before, this raised about the
    missing source, because the middleware was never looked at.
    """
    config = {
        "id": "mw-from-config",
        "queries": [
            {
                "id": "q",
                "query": CITY_QUERY,
                "sources": [{"id": "orders", "pipeline": ["flatten"]}],
                "middleware": [{"name": "flatten"}],
            }
        ],
    }

    with pytest.raises(DrasiError) as caught:
        await Drasi.from_config(config)

    assert "kind" in str(caught.value)
