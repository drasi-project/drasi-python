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

"""The optional stores and credentials passed to `Drasi.create`."""

from __future__ import annotations

from pathlib import Path

import pytest

from drasi import ConfigError, Drasi, DrasiError, UnknownKindError, host_info

from ..conftest import EngineFactory
from .helpers import wait_for_at_least_rows, wait_for_query_running, wait_for_rows

COUNTER_QUERY = "MATCH (c:Counter) RETURN c.value AS value"
ORDERS_QUERY = "MATCH (o:Order) RETURN o.id AS id"


def rocksdb_available() -> bool:
    """Ask the build, not the environment.

    RocksDB is behind a Cargo feature, so availability depends on how the
    extension was compiled. Gating on an environment variable meant these tests
    disagreed with reality whenever the two drifted — notably for release
    wheels, which are built with the feature but tested without the variable.
    """
    return "rocksdb" in host_info()["index_backends"]


# ------------------------------------------------------------------- validation


async def test_create_accepts_no_options_at_all() -> None:
    async with await Drasi.create("t-bare") as drasi:
        assert await drasi.is_running() is False


async def test_state_store_requires_a_known_kind(tmp_path: Path) -> None:
    with pytest.raises(UnknownKindError) as caught:
        await Drasi.create("t", state_store={"kind": "sqlite", "path": str(tmp_path)})  # pyright: ignore[reportArgumentType]  # invalid on purpose
    assert caught.value.code == "UNKNOWN_STATE_STORE_KIND"


async def test_state_store_requires_a_path() -> None:
    with pytest.raises(ConfigError) as caught:
        await Drasi.create("t", state_store={"kind": "redb"})  # pyright: ignore[reportArgumentType]  # invalid on purpose
    assert caught.value.code == "STATE_STORE_PATH_REQUIRED"


async def test_index_store_requires_a_path() -> None:
    with pytest.raises(ConfigError) as caught:
        await Drasi.create("t", index_store={"kind": "rocksdb"})
    assert caught.value.code == "INDEX_STORE_PATH_REQUIRED"


async def test_index_store_requires_a_known_kind(tmp_path: Path) -> None:
    with pytest.raises(UnknownKindError) as caught:
        await Drasi.create("t", index_store={"kind": "lmdb", "path": str(tmp_path)})  # pyright: ignore[reportArgumentType]  # invalid on purpose
    assert caught.value.code == "UNKNOWN_INDEX_STORE_KIND"


async def test_identity_requires_a_kind() -> None:
    with pytest.raises(ConfigError) as caught:
        await Drasi.create("t", identity={"username": "u", "password": "p"})
    assert caught.value.code == "IDENTITY_KIND_REQUIRED"


async def test_identity_rejects_an_unknown_kind() -> None:
    with pytest.raises(UnknownKindError) as caught:
        await Drasi.create("t", identity={"kind": "kerberos"})  # pyright: ignore[reportArgumentType]  # invalid on purpose
    assert caught.value.code == "UNKNOWN_IDENTITY_KIND"


@pytest.mark.parametrize(
    "identity",
    [
        {"kind": "password", "username": "u"},
        {"kind": "password", "password": "p"},
        {"kind": "token"},
    ],
)
async def test_identity_requires_its_own_fields(identity: dict[str, str]) -> None:
    with pytest.raises(ConfigError) as caught:
        await Drasi.create("t", identity=identity)  # pyright: ignore[reportArgumentType]
    assert caught.value.code == "IDENTITY_CONFIG_INVALID"


async def test_options_are_validated_before_awaiting() -> None:
    """A bad option should raise on the call, not on the await."""
    with pytest.raises(DrasiError):
        Drasi.create("t", state_store={"kind": "nope", "path": "/tmp/x"})  # pyright: ignore[reportArgumentType]  # invalid on purpose


# ------------------------------------------------------------------ state store


async def test_a_redb_state_store_is_accepted_and_written(tmp_path: Path) -> None:
    path = tmp_path / "state.redb"
    async with await Drasi.create(
        "t-redb", state_store={"kind": "redb", "path": str(path)}
    ) as drasi:
        await drasi.start()
        await drasi.add_python_source("s")
        await drasi.add_query("q", ORDERS_QUERY, ["s"])
        await wait_for_query_running(drasi, "q")
        await drasi.push_change(
            "s", {"op": "insert", "id": "o1", "labels": ["Order"], "properties": {"id": "o1"}}
        )
        assert await wait_for_rows(drasi, "q") == [{"id": "o1"}]

    assert path.exists(), "the state store file should have been created"


# ------------------------------------------------------------------ index store


@pytest.mark.skipif(not rocksdb_available(), reason="built without the rocksdb feature")
async def test_a_rocksdb_index_store_backs_query_state(tmp_path: Path) -> None:
    path = tmp_path / "index"
    async with await Drasi.create(
        "t-rocksdb", index_store={"kind": "rocksdb", "path": str(path)}
    ) as drasi:
        await drasi.start()
        await drasi.add_python_source("s")
        await drasi.add_query("q", ORDERS_QUERY, ["s"])
        await wait_for_query_running(drasi, "q")
        await drasi.push_change(
            "s", {"op": "insert", "id": "o1", "labels": ["Order"], "properties": {"id": "o1"}}
        )
        assert await wait_for_rows(drasi, "q") == [{"id": "o1"}]

    assert path.is_dir() and any(path.iterdir()), "the index should be on disk"


@pytest.mark.skipif(rocksdb_available(), reason="built with the rocksdb feature")
async def test_rocksdb_without_the_feature_says_so(tmp_path: Path) -> None:
    with pytest.raises(UnknownKindError) as caught:
        await Drasi.create("t", index_store={"kind": "rocksdb", "path": str(tmp_path)})
    assert "rocksdb" in str(caught.value).lower()


# ---------------------------------------------------------------------- secrets


async def test_secrets_are_accepted_without_plugins() -> None:
    async with await Drasi.create("t-secrets", secrets={"A": "1", "B": "2"}) as drasi:
        await drasi.start()
        assert await drasi.is_running() is True


@pytest.mark.plugins
async def test_a_plugin_resolves_a_secret_reference(engine_factory: EngineFactory) -> None:
    """The point of the secret store: a plugin reading a value it cannot see.

    A plugin serialises `{"kind": "Secret", "name": ...}` and calls back into
    the host, so this only works if a config resolver was injected at load time.
    """
    plugins = Path(__file__).resolve().parents[2] / "plugins"
    if not any(plugins.glob("*drasi_source_mock*")):
        pytest.skip("run `python scripts/build_plugins.py` first")

    async with await engine_factory("t-plugin-secret", secrets={"INTERVAL": "60"}) as drasi:
        await drasi.load_plugins(str(plugins))
        await drasi.start()
        await drasi.add_source(
            "mock",
            "counters",
            {"dataType": {"type": "counter"}, "intervalMs": {"kind": "Secret", "name": "INTERVAL"}},
        )
        await drasi.add_query("counts", COUNTER_QUERY, ["counters"])
        await wait_for_query_running(drasi, "counts")

        rows = await wait_for_at_least_rows(drasi, "counts", count=10)
        assert all("value" in row for row in rows)


@pytest.mark.plugins
async def test_a_plugin_resolves_an_environment_variable(
    engine_factory: EngineFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugins = Path(__file__).resolve().parents[2] / "plugins"
    if not any(plugins.glob("*drasi_source_mock*")):
        pytest.skip("run `python scripts/build_plugins.py` first")

    monkeypatch.setenv("DRASI_TEST_INTERVAL", "60")

    async with await engine_factory("t-plugin-env") as drasi:
        await drasi.load_plugins(str(plugins))
        await drasi.start()
        await drasi.add_source(
            "mock",
            "counters",
            {
                "dataType": {"type": "counter"},
                "intervalMs": {
                    "kind": "EnvironmentVariable",
                    "name": "DRASI_TEST_INTERVAL",
                },
            },
        )
        await drasi.add_query("counts", COUNTER_QUERY, ["counters"])
        await wait_for_query_running(drasi, "counts")

        assert len(await wait_for_at_least_rows(drasi, "counts", count=10)) >= 10


@pytest.mark.plugins
async def test_a_missing_secret_is_reported_rather_than_silently_empty(
    engine_factory: EngineFactory,
) -> None:
    plugins = Path(__file__).resolve().parents[2] / "plugins"
    if not any(plugins.glob("*drasi_source_mock*")):
        pytest.skip("run `python scripts/build_plugins.py` first")

    async with await engine_factory("t-missing-secret") as drasi:
        await drasi.load_plugins(str(plugins))
        await drasi.start()
        with pytest.raises(DrasiError):
            await drasi.add_source(
                "mock",
                "counters",
                {
                    "dataType": {"type": "counter"},
                    "intervalMs": {"kind": "Secret", "name": "NOT_PROVIDED"},
                },
            )
