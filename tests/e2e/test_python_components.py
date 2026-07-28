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

"""Tier 1: a Python source feeds a continuous query that drives a Python reaction.

These tests need no plugins, no network and no Docker.
"""

from __future__ import annotations

from typing import Any

import pytest

from drasi import Drasi, DrasiError, SourceError, UnknownKindError

from .helpers import (
    collect_events,
    wait_for,
    wait_for_query_running,
    wait_for_result,
    wait_for_rows,
)

OPEN_ORDERS = "MATCH (o:Order) WHERE o.status = 'open' RETURN o.id AS id, o.total AS total"


async def test_pushed_change_reaches_the_query(engine: Drasi) -> None:
    await engine.add_python_source("orders")
    await engine.add_query("open", OPEN_ORDERS, ["orders"])
    await engine.start()

    await engine.push_change(
        "orders",
        {
            "op": "insert",
            "id": "o1",
            "labels": ["Order"],
            "properties": {"id": "o1", "status": "open", "total": 42},
        },
    )

    rows = await wait_for_rows(engine, "open")
    assert rows == [{"id": "o1", "total": 42}]


async def test_reaction_receives_add_update_and_delete(engine: Drasi) -> None:
    await engine.add_python_source("orders")
    await engine.add_query("open", OPEN_ORDERS, ["orders"])
    events = await collect_events(engine, "watch", ["open"])
    await engine.start()

    await engine.push_change(
        "orders",
        {
            "op": "insert",
            "id": "o1",
            "labels": ["Order"],
            "properties": {"id": "o1", "status": "open", "total": 10},
        },
    )
    diffs = await events.take(1)
    assert diffs[0]["type"] == "ADD"
    assert diffs[0]["data"] == {"id": "o1", "total": 10}

    await engine.push_change(
        "orders",
        {
            "op": "update",
            "id": "o1",
            "labels": ["Order"],
            "properties": {"id": "o1", "status": "open", "total": 99},
        },
    )
    diffs = await events.take(1)
    assert diffs[0]["type"] == "UPDATE"
    assert diffs[0]["after"] == {"id": "o1", "total": 99}

    # Closing the order takes it out of the result set.
    await engine.push_change(
        "orders",
        {
            "op": "update",
            "id": "o1",
            "labels": ["Order"],
            "properties": {"id": "o1", "status": "closed", "total": 99},
        },
    )
    diffs = await events.take(1)
    assert diffs[0]["type"] == "DELETE"

    assert await engine.get_query_results("open") == []


async def test_delete_removes_the_row(engine: Drasi) -> None:
    await engine.add_python_source("orders")
    await engine.add_query("open", OPEN_ORDERS, ["orders"])
    await engine.start()

    await engine.push_change(
        "orders",
        {
            "op": "insert",
            "id": "o1",
            "labels": ["Order"],
            "properties": {"status": "open", "total": 1},
        },
    )
    await wait_for_rows(engine, "open")

    await engine.push_change("orders", {"op": "delete", "id": "o1", "labels": ["Order"]})
    assert await wait_for_rows(engine, "open", count=0) == []


@pytest.mark.parametrize("insert_op", ["insert", "add", "INSERT"])
async def test_insert_aliases_are_accepted(engine: Drasi, insert_op: str) -> None:
    await engine.add_python_source("orders")
    await engine.add_query("open", OPEN_ORDERS, ["orders"])
    await engine.start()

    await engine.push_change(
        "orders",
        {
            "op": insert_op,
            "id": "o1",
            "labels": ["Order"],
            "properties": {"id": "o1", "status": "open", "total": 7},
        },
    )
    assert await wait_for_rows(engine, "open") == [{"id": "o1", "total": 7}]


async def test_remove_is_an_alias_for_delete(engine: Drasi) -> None:
    await engine.add_python_source("orders")
    await engine.add_query("open", OPEN_ORDERS, ["orders"])
    await engine.start()

    await engine.push_change(
        "orders",
        {
            "op": "add",
            "id": "o1",
            "labels": ["Order"],
            "properties": {"status": "open", "total": 1},
        },
    )
    await wait_for_rows(engine, "open")
    await engine.push_change("orders", {"op": "remove", "id": "o1", "labels": ["Order"]})
    assert await wait_for_rows(engine, "open", count=0) == []


async def test_relations_connect_two_nodes(engine: Drasi) -> None:
    await engine.add_python_source("graph")
    await engine.add_query(
        "owned",
        "MATCH (c:Customer)-[:OWNS]->(o:Order) RETURN c.name AS customer, o.id AS order_id",
        ["graph"],
    )
    await engine.start()

    await engine.push_change(
        "graph",
        {"op": "insert", "id": "c1", "labels": ["Customer"], "properties": {"name": "Ada"}},
    )
    await engine.push_change(
        "graph", {"op": "insert", "id": "o1", "labels": ["Order"], "properties": {"id": "o1"}}
    )
    await engine.push_change(
        "graph",
        {"op": "insert", "id": "r1", "labels": ["OWNS"], "start_id": "c1", "end_id": "o1"},
    )

    assert await wait_for_rows(engine, "owned") == [{"customer": "Ada", "order_id": "o1"}]


async def test_node_style_camel_case_relation_keys_are_accepted(engine: Drasi) -> None:
    """`startId`/`endId` come from the Node.js API and must keep working."""
    await engine.add_python_source("graph")
    await engine.add_query(
        "owned",
        "MATCH (c:Customer)-[:OWNS]->(o:Order) RETURN c.name AS customer",
        ["graph"],
    )
    await engine.start()

    await engine.push_change(
        "graph",
        {"op": "insert", "id": "c1", "labels": ["Customer"], "properties": {"name": "Grace"}},
    )
    await engine.push_change("graph", {"op": "insert", "id": "o1", "labels": ["Order"]})
    await engine.push_change(
        "graph", {"op": "insert", "id": "r1", "labels": ["OWNS"], "startId": "c1", "endId": "o1"}
    )

    assert await wait_for_rows(engine, "owned") == [{"customer": "Grace"}]


async def test_gql_queries_are_supported(engine: Drasi) -> None:
    await engine.add_python_source("orders")
    await engine.add_query(
        "all",
        "MATCH (o:Order) RETURN o.id AS id",
        ["orders"],
        language="gql",
    )
    await engine.start()

    await engine.push_change(
        "orders", {"op": "insert", "id": "o1", "labels": ["Order"], "properties": {"id": "o1"}}
    )
    assert await wait_for_rows(engine, "all") == [{"id": "o1"}]


async def test_property_values_round_trip_through_python_types(engine: Drasi) -> None:
    await engine.add_python_source("things")
    await engine.add_query(
        "all",
        "MATCH (t:Thing) RETURN t.text AS text, t.number AS number, t.ratio AS ratio, "
        "t.flag AS flag, t.missing AS missing, t.tags AS tags",
        ["things"],
    )
    await engine.start()

    await engine.push_change(
        "things",
        {
            "op": "insert",
            "id": "t1",
            "labels": ["Thing"],
            "properties": {
                "text": "hello",
                "number": 7,
                "ratio": 1.5,
                "flag": True,
                "missing": None,
                "tags": ["a", "b"],
            },
        },
    )

    rows = await wait_for_rows(engine, "all")
    row: dict[str, Any] = rows[0]
    assert row["text"] == "hello"
    assert row["number"] == 7 and isinstance(row["number"], int)
    assert row["ratio"] == 1.5
    # `bool` is a subclass of `int`, so an unordered check would silently pass.
    assert row["flag"] is True
    assert row["missing"] is None
    assert row["tags"] == ["a", "b"]


async def test_element_id_is_not_automatically_a_property(engine: Drasi) -> None:
    """A change's `id` is the graph key, not a property.

    Queries that select `o.id` read a *property* named `id`, so a source must
    emit it explicitly. Getting this wrong yields silent `None`s rather than an
    error, which is why it is pinned here.
    """
    await engine.add_python_source("orders")
    await engine.add_query("all", "MATCH (o:Order) RETURN o.id AS id", ["orders"])
    await engine.start()

    await engine.push_change(
        "orders", {"op": "insert", "id": "o1", "labels": ["Order"], "properties": {}}
    )
    assert await wait_for_rows(engine, "all") == [{"id": None}]

    await engine.push_change(
        "orders",
        {"op": "update", "id": "o1", "labels": ["Order"], "properties": {"id": "o1"}},
    )
    await wait_for_result(engine, "all", [{"id": "o1"}])


async def test_list_queries_reports_registered_queries(engine: Drasi) -> None:
    await engine.add_python_source("orders")
    await engine.add_query("open", OPEN_ORDERS, ["orders"])
    await engine.start()

    ids = [query_id for query_id, _ in await engine.list_queries()]
    assert "open" in ids


async def test_stopped_query_can_be_restarted(engine: Drasi) -> None:
    await engine.add_python_source("orders")
    await engine.add_query("open", OPEN_ORDERS, ["orders"])
    await engine.start()

    await engine.stop_query("open")
    await engine.start_query("open")

    await engine.push_change(
        "orders",
        {
            "op": "insert",
            "id": "o1",
            "labels": ["Order"],
            "properties": {"id": "o1", "status": "open", "total": 3},
        },
    )
    assert await wait_for_rows(engine, "open") == [{"id": "o1", "total": 3}]


async def test_stopped_query_results_are_rejected(engine: Drasi) -> None:
    await engine.add_python_source("orders")
    await engine.add_query("open", OPEN_ORDERS, ["orders"])
    await engine.start()
    await engine.wait_for_query("open")
    await engine.push_change(
        "orders",
        {
            "op": "insert",
            "id": "o1",
            "labels": ["Order"],
            "properties": {"id": "o1", "status": "open", "total": 3},
        },
    )
    await wait_for_rows(engine, "open")

    await engine.stop_query("open")

    with pytest.raises(DrasiError) as caught:
        await engine.get_query_results("open")
    assert caught.value.code == "ENGINE_FAILURE"
    assert "not running" in str(caught.value)


async def test_running_query_can_be_updated_in_place(engine: Drasi) -> None:
    await engine.start()
    await engine.add_python_source("orders")
    await engine.add_query("open", "MATCH (o:Order) RETURN o.id AS id", ["orders"])
    await wait_for_query_running(engine, "open")
    await engine.push_change(
        "orders",
        {
            "op": "insert",
            "id": "o1",
            "labels": ["Order"],
            "properties": {"id": "o1", "status": "open", "total": 3},
        },
    )
    assert await wait_for_rows(engine, "open") == [{"id": "o1"}]

    # Updating a query restarts it, so it is briefly not running and reading
    # results in that window raises rather than returning an empty list.
    await engine.update_query("open", OPEN_ORDERS, ["orders"])
    await wait_for_query_running(engine, "open")
    await wait_for_rows(engine, "open", count=0)
    await engine.push_change(
        "orders",
        {
            "op": "update",
            "id": "o1",
            "labels": ["Order"],
            "properties": {"id": "o1", "status": "open", "total": 4},
        },
    )
    await wait_for_result(engine, "open", [{"id": "o1", "total": 4}])


async def test_removed_query_is_gone(engine: Drasi) -> None:
    await engine.add_python_source("orders")
    await engine.add_query("open", OPEN_ORDERS, ["orders"])
    await engine.start()
    await engine.remove_query("open")

    assert [query_id for query_id, _ in await engine.list_queries()] == []


async def test_running_source_without_dependents_can_be_removed(engine: Drasi) -> None:
    await engine.add_python_source("orders")
    await engine.start()

    await engine.remove_source("orders")

    assert "orders" not in dict(await engine.list_sources())
    with pytest.raises(SourceError) as caught:
        await engine.push_change("orders", {"op": "insert", "id": "o1"})
    assert caught.value.code == "NO_PY_SOURCE"


async def test_source_registered_without_auto_start_can_be_started(engine: Drasi) -> None:
    await engine.add_python_source("orders", auto_start=False)
    await engine.start()

    assert await engine.get_source_status("orders") == "Added"

    await engine.start_source("orders")

    assert await engine.get_source_status("orders") == "Running"


async def test_running_source_with_dependents_is_not_removed(engine: Drasi) -> None:
    await engine.add_python_source("orders")
    await engine.add_query("open", OPEN_ORDERS, ["orders"])
    await engine.start()
    await wait_for_query_running(engine, "open")

    with pytest.raises(DrasiError) as caught:
        await engine.remove_source("orders")
    assert caught.value.code == "ENGINE_FAILURE"
    assert "Depended on by: open" in str(caught.value)
    assert "orders" in dict(await engine.list_sources())


async def test_running_reaction_can_be_removed(engine: Drasi) -> None:
    await engine.add_python_source("orders")
    await engine.add_query("open", OPEN_ORDERS, ["orders"])
    seen: list[dict[str, Any]] = []
    await engine.add_python_reaction("watch", ["open"], seen.append)
    await engine.start()
    await wait_for_query_running(engine, "open")
    assert "watch" in dict(await engine.list_reactions())

    await engine.remove_reaction("watch")

    assert "watch" not in dict(await engine.list_reactions())
    await engine.push_change(
        "orders",
        {
            "op": "insert",
            "id": "o1",
            "labels": ["Order"],
            "properties": {"id": "o1", "status": "open", "total": 1},
        },
    )
    await wait_for_rows(engine, "open")
    assert seen == []


async def test_stopped_reaction_replays_missed_results_when_restarted(engine: Drasi) -> None:
    await engine.add_python_source("orders")
    await engine.add_query("open", OPEN_ORDERS, ["orders"])
    seen: list[dict[str, Any]] = []
    await engine.add_python_reaction("watch", ["open"], seen.append)
    await engine.start()
    await wait_for_query_running(engine, "open")

    await engine.stop_reaction("watch")
    assert await engine.get_reaction_status("watch") == "Stopped"
    await engine.push_change(
        "orders",
        {
            "op": "insert",
            "id": "o1",
            "labels": ["Order"],
            "properties": {"id": "o1", "status": "open", "total": 1},
        },
    )
    await wait_for_rows(engine, "open")
    assert seen == []

    await engine.start_reaction("watch")

    await wait_for(lambda: len(seen) == 1, description="restarted reaction to replay result")
    assert seen[0]["results"][0]["data"] == {"id": "o1", "total": 1}


@pytest.mark.parametrize("component", ["source", "query", "reaction"])
async def test_duplicate_component_ids_are_rejected(engine: Drasi, component: str) -> None:
    await engine.add_python_source("orders")
    if component == "source":
        duplicate = engine.add_python_source("orders")
    else:
        await engine.add_query("open", OPEN_ORDERS, ["orders"])
        if component == "query":
            duplicate = engine.add_query("open", OPEN_ORDERS, ["orders"])
        else:
            await engine.add_python_reaction("watch", ["open"], lambda _: None)
            duplicate = engine.add_python_reaction("watch", ["open"], lambda _: None)

    with pytest.raises(DrasiError) as caught:
        await duplicate
    assert caught.value.code == "ENGINE_FAILURE"
    assert "already exists" in str(caught.value)


# --------------------------------------------------------------------- errors


async def test_unknown_query_language_is_rejected(engine: Drasi) -> None:
    with pytest.raises(UnknownKindError) as caught:
        await engine.add_query("q", "MATCH (n) RETURN n", ["s"], language="sparql")
    assert caught.value.code == "UNKNOWN_QUERY_LANGUAGE"


async def test_pushing_to_an_unknown_source_is_rejected(engine: Drasi) -> None:
    await engine.start()
    with pytest.raises(SourceError) as caught:
        await engine.push_change("nope", {"op": "insert", "id": "o1"})
    assert caught.value.code == "NO_PY_SOURCE"


async def test_change_requires_an_op(engine: Drasi) -> None:
    await engine.add_python_source("orders")
    with pytest.raises(SourceError) as caught:
        await engine.push_change("orders", {"id": "o1"})
    assert caught.value.code == "CHANGE_OP_REQUIRED"


async def test_change_requires_an_id(engine: Drasi) -> None:
    await engine.add_python_source("orders")
    with pytest.raises(SourceError) as caught:
        await engine.push_change("orders", {"op": "insert"})
    assert caught.value.code == "CHANGE_ID_REQUIRED"


async def test_change_must_be_a_mapping(engine: Drasi) -> None:
    await engine.add_python_source("orders")
    with pytest.raises(SourceError) as caught:
        await engine.push_change("orders", ["not", "a", "mapping"])
    assert caught.value.code == "CHANGE_NOT_OBJECT"


async def test_unknown_change_op_is_rejected(engine: Drasi) -> None:
    await engine.add_python_source("orders")
    with pytest.raises(DrasiError) as caught:
        await engine.push_change("orders", {"op": "upsert", "id": "o1"})
    assert caught.value.code == "UNKNOWN_CHANGE_OP"


async def test_half_a_relation_is_rejected(engine: Drasi) -> None:
    """Treating this as a node would silently drop the relation."""
    await engine.add_python_source("graph")
    with pytest.raises(SourceError) as caught:
        await engine.push_change(
            "graph", {"op": "insert", "id": "r1", "labels": ["OWNS"], "start_id": "c1"}
        )
    assert caught.value.code == "RELATION_REQUIRES_BOTH_ENDS"


async def test_a_non_callable_reaction_is_rejected(engine: Drasi) -> None:
    with pytest.raises(DrasiError) as caught:
        await engine.add_python_reaction("bad", ["open"], "not callable")
    assert caught.value.code == "CONFIG_INVALID"


async def test_errors_are_raised_before_awaiting(engine: Drasi) -> None:
    """Validation failures must not require the caller to await to observe them.

    napi-rs can only attach an error code to a synchronous throw, so the Node.js
    binding smuggles codes into async messages. PyO3 has no such limitation.
    """
    await engine.add_python_source("orders")
    pending = None
    try:
        pending = engine.push_change("orders", {"id": "missing-op"})
    except DrasiError as err:
        assert err.code == "CHANGE_OP_REQUIRED"
    finally:
        if pending is not None:  # pragma: no cover - only on regression
            pending.close()
            pytest.fail("push_change returned an awaitable instead of raising")


async def test_every_error_is_a_drasi_error(engine: Drasi) -> None:
    assert issubclass(SourceError, DrasiError)
    assert issubclass(UnknownKindError, DrasiError)
