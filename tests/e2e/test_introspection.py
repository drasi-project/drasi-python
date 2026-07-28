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

"""Introspection: metrics, schema and component status."""

from __future__ import annotations

from pathlib import Path

import pytest

from drasi import Drasi, DrasiError, UnknownKindError

from .helpers import wait_for_query_running, wait_for_rows

ORDERS_QUERY = "MATCH (o:Order) RETURN o.id AS id"
COUNTER_QUERY = "MATCH (c:Counter) RETURN c.value AS value"
MOCK_CONFIG = {"dataType": {"type": "counter"}, "intervalMs": 50}


def plugin_dir() -> Path:
    directory = Path(__file__).resolve().parents[2] / "plugins"
    if not any(directory.glob("*drasi_source_mock*")):
        pytest.skip("run `python scripts/build_plugins.py` first")
    return directory


async def running(engine: Drasi) -> Drasi:
    await engine.start()
    await engine.add_python_source("orders")
    await engine.add_query("q", ORDERS_QUERY, ["orders"])
    await wait_for_query_running(engine, "q")
    return engine


# --------------------------------------------------------------------- metrics


async def test_query_metrics_report_progress(engine: Drasi) -> None:
    drasi = await running(engine)
    await drasi.push_change(
        "orders", {"op": "insert", "id": "o1", "labels": ["Order"], "properties": {"id": "o1"}}
    )
    await wait_for_rows(drasi, "q")

    metrics = await drasi.get_query_metrics("q")
    assert metrics["live_results_count"] == 1
    # Every documented field should be present, not just the ones we assert on.
    assert set(metrics) == {
        "outbox_size",
        "outbox_earliest_seq",
        "outbox_latest_seq",
        "result_seq_advances",
        "live_results_count",
        "outer_transaction_duration_ns_last",
        "outer_transaction_duration_ns_max",
        "snapshot_fetch_count",
    }
    assert all(isinstance(value, int) for value in metrics.values())


async def test_reaction_metrics_are_keyed_by_query(engine: Drasi) -> None:
    drasi = await running(engine)
    await drasi.add_python_reaction("watch", ["q"], lambda _: None)

    metrics = await drasi.get_reaction_metrics("watch")
    assert "q" in metrics
    assert "checkpoint_sequence" in metrics["q"]


async def test_lifecycle_metrics_are_reported(engine: Drasi) -> None:
    drasi = await running(engine)
    metrics = await drasi.get_lifecycle_metrics()

    assert set(metrics) == {
        "startup_rejection_durable_no_store",
        "startup_rejection_durable_on_volatile",
        "startup_rejection_snapshot_skip_gap",
        "startup_rejection_no_snapshot_auto_reset",
        "auto_reset_completions",
        "hash_mismatch_count",
    }


async def test_metrics_for_an_unknown_component_are_rejected(engine: Drasi) -> None:
    await engine.start()
    with pytest.raises(DrasiError):
        await engine.get_query_metrics("nope")


# ---------------------------------------------------------------------- schema


async def test_a_source_without_a_schema_reports_none(engine: Drasi) -> None:
    drasi = await running(engine)
    assert await drasi.get_source_schema("orders") is None


async def test_the_graph_schema_uses_snake_case_keys(engine: Drasi) -> None:
    """The engine serialises these as camelCase; the Python API is snake_case."""
    drasi = await running(engine)
    schema = await drasi.get_graph_schema()

    assert "sources_without_schema" in schema
    assert "sourcesWithoutSchema" not in schema
    assert set(schema) >= {"nodes", "relations", "sources_without_schema"}


@pytest.mark.plugins
async def test_a_plugin_source_describes_its_schema(engine: Drasi) -> None:
    await engine.load_plugins(str(plugin_dir()))
    await engine.start()
    await engine.add_source("mock", "counters", MOCK_CONFIG)

    schema = await engine.get_source_schema("counters")
    assert schema is not None
    labels = [node["label"] for node in schema["nodes"]]
    assert "Counter" in labels
    # Nested keys are converted too.
    properties = schema["nodes"][labels.index("Counter")]["properties"]
    assert any("data_type" in prop for prop in properties)


# ---------------------------------------------------------------------- status


async def test_component_statuses_are_reported(engine: Drasi) -> None:
    drasi = await running(engine)
    await drasi.add_python_reaction("watch", ["q"], lambda _: None)

    assert await drasi.get_query_status("q") == "Running"
    assert await drasi.get_source_status("orders") == "Running"
    assert await drasi.get_reaction_status("watch") == "Running"


async def test_status_reflects_stopping_a_component(engine: Drasi) -> None:
    drasi = await running(engine)
    await drasi.stop_source("orders")
    assert await drasi.get_source_status("orders") == "Stopped"


async def test_status_of_an_unknown_component_is_rejected(engine: Drasi) -> None:
    await engine.start()
    with pytest.raises(DrasiError):
        await engine.get_source_status("nope")


# ---------------------------------------------------------------------- update


@pytest.mark.plugins
async def test_a_source_can_be_reconfigured_in_place(engine: Drasi) -> None:
    await engine.load_plugins(str(plugin_dir()))
    await engine.start()
    await engine.add_source("mock", "counters", MOCK_CONFIG)
    await engine.add_query("counts", COUNTER_QUERY, ["counters"])
    await wait_for_query_running(engine, "counts")

    await engine.update_source(
        "mock", "counters", {"dataType": {"type": "counter"}, "intervalMs": 200}
    )

    assert "counters" in dict(await engine.list_sources())


@pytest.mark.plugins
async def test_a_reaction_can_be_reconfigured_in_place(engine: Drasi) -> None:
    await engine.load_plugins(str(plugin_dir()))
    await engine.start()
    await engine.add_source("mock", "counters", MOCK_CONFIG)
    await engine.add_query("counts", COUNTER_QUERY, ["counters"])
    await engine.add_reaction("log", "logger", ["counts"], {})

    await engine.update_reaction("log", "logger", ["counts"], {})

    assert "logger" in dict(await engine.list_reactions())


async def test_updating_an_unknown_kind_is_rejected(engine: Drasi) -> None:
    await engine.start()
    with pytest.raises(UnknownKindError) as caught:
        await engine.update_source("postgres", "db", {})
    assert caught.value.code == "UNKNOWN_SOURCE_KIND"


async def test_unknown_bootstrap_schema_kind_is_rejected(engine: Drasi) -> None:
    with pytest.raises(UnknownKindError) as caught:
        await engine.bootstrap_config_schema("missing")
    assert caught.value.code == "UNKNOWN_BOOTSTRAP_KIND"
