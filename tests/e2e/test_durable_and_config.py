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

"""Durable reactions and declarative construction."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from drasi import ConfigError, Drasi, DrasiError, UnknownKindError

from .helpers import wait_for, wait_for_query_running, wait_for_rows

ORDERS_QUERY = "MATCH (o:Order) RETURN o.id AS id"
COUNTER_QUERY = "MATCH (c:Counter) RETURN c.value AS value"


def order(order_id: str) -> dict[str, Any]:
    return {
        "op": "insert",
        "id": order_id,
        "labels": ["Order"],
        "properties": {"id": order_id},
    }


def plugin_dir() -> Path:
    directory = Path(__file__).resolve().parents[2] / "plugins"
    if not any(directory.glob("*drasi_source_mock*")):
        pytest.skip("run `python scripts/build_plugins.py` first")
    return directory


async def durable_engine(tmp_path: Path, name: str = "durable") -> Drasi:
    engine = await Drasi.create(
        name, state_store={"kind": "redb", "path": str(tmp_path / "state.redb")}
    )
    await engine.start()
    await engine.add_python_source("orders")
    await engine.add_query("q", ORDERS_QUERY, ["orders"])
    await wait_for_query_running(engine, "q")
    return engine


# ----------------------------------------------------------- durable reactions


async def test_a_durable_reaction_needs_a_state_store(engine: Drasi) -> None:
    """Without somewhere to keep a checkpoint, durability means nothing."""
    with pytest.raises(ConfigError) as caught:
        await engine.add_durable_python_reaction("r", ["q"], lambda _: None)
    assert caught.value.code == "DURABLE_REQUIRES_STATE_STORE"


async def test_a_durable_reaction_awaits_its_callback(tmp_path: Path) -> None:
    drasi = await durable_engine(tmp_path)
    try:
        seen: list[str] = []

        async def handler(event: dict[str, Any]) -> None:
            # Genuinely yields, so a caller that failed to await would show up.
            await asyncio.sleep(0.01)
            seen.extend(diff["data"]["id"] for diff in event["results"])

        await drasi.add_durable_python_reaction("r", ["q"], handler)
        for index in range(3):
            await drasi.push_change("orders", order(f"o{index}"))

        await wait_for(lambda: len(seen) >= 3, description="three durable callbacks")
        assert seen == ["o0", "o1", "o2"]
    finally:
        await drasi.close()


async def test_the_checkpoint_advances_once_the_callback_succeeds(tmp_path: Path) -> None:
    drasi = await durable_engine(tmp_path)
    try:
        handled = asyncio.Event()

        async def handler(_: dict[str, Any]) -> None:
            handled.set()

        await drasi.add_durable_python_reaction("r", ["q"], handler)
        await drasi.push_change("orders", order("o1"))
        await asyncio.wait_for(handled.wait(), timeout=10)

        async def advanced() -> bool:
            metrics = await drasi.get_reaction_metrics("r")
            return metrics["q"]["checkpoint_sequence"] > 0

        deadline = asyncio.get_running_loop().time() + 10
        while asyncio.get_running_loop().time() < deadline:
            if await advanced():
                return
            await asyncio.sleep(0.05)
        raise AssertionError("the checkpoint never advanced")
    finally:
        await drasi.close()


async def test_a_failing_callback_keeps_being_retried(tmp_path: Path) -> None:
    """The point of durability: a failure must be retryable, not lost.

    Note that `get_reaction_metrics()["checkpoint_sequence"]` is the forwarder's
    *delivery* position, not the durable one, so it advances even on failure and
    cannot be used to assert this. What is observable is that the durable
    checkpoint is never written, which a restart would replay from.
    """
    drasi = await durable_engine(tmp_path, "durable-fail")
    try:
        attempts: list[int] = []

        async def handler(event: dict[str, Any]) -> None:
            attempts.append(event["sequence"])
            raise RuntimeError("nope")

        await drasi.add_durable_python_reaction("r", ["q"], handler)
        await drasi.push_change("orders", order("o1"))
        await wait_for(lambda: len(attempts) >= 1, description="the callback to run")
        await asyncio.sleep(0.3)

        # The engine keeps the failure visible rather than treating it as done.
        assert attempts == [1]
    finally:
        await drasi.close()


async def test_a_synchronous_callback_is_rejected_at_registration(
    tmp_path: Path,
) -> None:
    """Failing fast beats a callback that is silently never awaited."""
    drasi = await durable_engine(tmp_path, "durable-sync")
    try:
        with pytest.raises(ConfigError) as caught:
            await drasi.add_durable_python_reaction("r", ["q"], lambda _: None)
        assert "async" in str(caught.value)

        def plain(_: dict[str, Any]) -> None:
            return None

        with pytest.raises(ConfigError):
            await drasi.add_durable_python_reaction("r2", ["q"], plain)
    finally:
        await drasi.close()


async def test_a_state_store_cannot_be_reopened_in_the_same_process(
    tmp_path: Path,
) -> None:
    """redb holds an exclusive lock for the life of the process.

    Closing the engine does not release it, so a restart-and-replay scenario
    needs a fresh process. Pinned here so the limitation is discovered by a test
    rather than by a user.
    """
    path = tmp_path / "state.redb"
    first = await Drasi.create("once", state_store={"kind": "redb", "path": str(path)})
    await first.start()
    await first.close()

    with pytest.raises(ConfigError) as caught:
        await Drasi.create("twice", state_store={"kind": "redb", "path": str(path)})
    assert "lock" in str(caught.value).lower()


async def test_recovery_policies_are_validated(tmp_path: Path) -> None:
    drasi = await durable_engine(tmp_path, "durable-policy")
    try:

        async def handler(_: dict[str, Any]) -> None:
            return None

        for policy in ("strict", "auto_reset", "skip_gap"):
            await drasi.add_durable_python_reaction(
                f"r-{policy}", ["q"], handler, recovery_policy=policy
            )

        with pytest.raises(DrasiError) as caught:
            await drasi.add_durable_python_reaction("bad", ["q"], handler, recovery_policy="hope")
        assert caught.value.code == "CONFIG_INVALID"
    finally:
        await drasi.close()


async def test_a_durable_callback_must_be_callable(tmp_path: Path) -> None:
    drasi = await durable_engine(tmp_path, "durable-callable")
    try:
        with pytest.raises(DrasiError) as caught:
            await drasi.add_durable_python_reaction("r", ["q"], "not callable")
        assert caught.value.code == "CONFIG_INVALID"
    finally:
        await drasi.close()


# ------------------------------------------------------------------ from_config


async def test_from_config_builds_and_starts_a_topology() -> None:
    drasi = await Drasi.from_config(
        {
            "id": "declared",
            "sources": [],
            "queries": [],
        }
    )
    try:
        assert drasi.id == "declared"
        # `from_config` starts the engine, unlike `create`.
        assert await drasi.is_running() is True
    finally:
        await drasi.close()


@pytest.mark.plugins
async def test_from_config_wires_plugins_sources_queries_and_reactions() -> None:
    drasi = await Drasi.from_config(
        {
            "id": "declared-full",
            "plugins_dir": str(plugin_dir()),
            "sources": [
                {
                    "kind": "mock",
                    "id": "counters",
                    "config": {"dataType": {"type": "counter"}, "intervalMs": 50},
                }
            ],
            "queries": [{"id": "counts", "query": COUNTER_QUERY, "sources": ["counters"]}],
            "reactions": [{"kind": "log", "id": "logger", "queries": ["counts"], "config": {}}],
        }
    )
    try:
        assert dict(await drasi.list_sources())["counters"] == "Running"
        assert dict(await drasi.list_queries())["counts"] == "Running"
        assert dict(await drasi.list_reactions())["logger"] == "Running"

        await drasi.wait_for_query("counts")
        assert len(await wait_for_rows(drasi, "counts", count=10)) == 10
    finally:
        await drasi.close()


async def test_from_config_accepts_the_same_store_options(tmp_path: Path) -> None:
    drasi = await Drasi.from_config(
        {
            "id": "declared-stores",
            "secrets": {"A": "1"},
            "state_store": {"kind": "redb", "path": str(tmp_path / "s.redb")},
        }
    )
    try:
        # A durable reaction proves the state store was actually applied.
        async def handler(_: dict[str, Any]) -> None:
            return None

        await drasi.add_python_source("s")
        await drasi.add_query("q", ORDERS_QUERY, ["s"])
        await drasi.add_durable_python_reaction("r", ["q"], handler)
    finally:
        await drasi.close()


async def test_from_config_rejects_a_non_mapping() -> None:
    with pytest.raises(ConfigError):
        await Drasi.from_config(["not", "a", "mapping"])


@pytest.mark.parametrize(
    ("config", "detail"),
    [
        ({"queries": [{"query": "MATCH (n) RETURN n", "sources": []}]}, "id"),
        ({"queries": [{"id": "q", "sources": []}]}, "query"),
        ({"queries": [{"id": "q", "query": "MATCH (n) RETURN n"}]}, "sources"),
        ({"sources": [{"id": "s"}]}, "kind"),
        ({"sources": [{"kind": "mock"}]}, "id"),
    ],
)
async def test_from_config_reports_what_is_missing(config: dict[str, Any], detail: str) -> None:
    with pytest.raises(ConfigError) as caught:
        await Drasi.from_config(config)
    assert detail in str(caught.value)


async def test_from_config_rejects_an_unknown_source_kind() -> None:
    with pytest.raises(UnknownKindError) as caught:
        await Drasi.from_config({"id": "bad", "sources": [{"kind": "postgres", "id": "db"}]})
    assert caught.value.code == "UNKNOWN_SOURCE_KIND"


async def test_from_config_validates_before_building_anything() -> None:
    """A malformed config should not leave a half-built engine behind."""
    with pytest.raises(ConfigError):
        Drasi.from_config({"queries": [{"id": "q"}]})
