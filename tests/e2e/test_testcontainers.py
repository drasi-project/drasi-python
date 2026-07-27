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

"""Tier 3: a real database behind a real plugin.

A Postgres container is started with logical replication enabled, the
`source/postgres` plugin is installed from the registry, and changes made with
SQL are asserted to flow through a continuous query. This is the closest thing
to how Drasi is actually used.

Requires Docker; the tests skip themselves when it is unavailable.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
import pytest_asyncio

from drasi import Drasi

from .helpers import collect_events, wait_for_query_running, wait_for_result, wait_for_rows

pytestmark = [
    pytest.mark.docker,
    pytest.mark.oci,
    pytest.mark.asyncio(loop_scope="module"),
]

POSTGRES_IMAGE = "postgres:16-alpine"

# The Postgres source labels nodes with the bare table name, and replicates only
# tables belonging to a publication it can find. Without the publication the
# source connects, reports Running, and then silently delivers nothing.
SCHEMA = """
CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    status TEXT NOT NULL
);
ALTER TABLE orders REPLICA IDENTITY FULL;
CREATE PUBLICATION drasi_publication FOR TABLE orders;
"""


@pytest.fixture(scope="module")
def postgres() -> Iterator[dict[str, Any]]:
    docker = pytest.importorskip("docker", reason="tier 3 requires Docker")
    try:
        docker.from_env().ping()
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Docker is not available: {exc}")

    from testcontainers.community.postgres import PostgresContainer

    container = PostgresContainer(POSTGRES_IMAGE, driver=None).with_command(
        # The source reads the write-ahead log, which only carries row data at
        # the `logical` level.
        "postgres -c wal_level=logical -c max_replication_slots=8 -c max_wal_senders=8"
    )
    with container as running:
        import psycopg

        dsn = (
            f"host={running.get_container_host_ip()} "
            f"port={running.get_exposed_port(5432)} "
            f"dbname={running.dbname} user={running.username} "
            f"password={running.password}"
        )
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(SCHEMA)

        yield {
            "dsn": dsn,
            "config": {
                "host": running.get_container_host_ip(),
                # The plugin deserialises this as a u16, so it must be a number.
                "port": int(running.get_exposed_port(5432)),
                "user": running.username,
                "password": running.password,
                "database": running.dbname,
                "tables": ["public.orders"],
                # Note the asymmetry: `tables` above is schema-qualified, but
                # `tableKeys.table` must be the bare table name. Qualify it here
                # and the key is silently not applied - updates arrive as a
                # second ADD instead of an UPDATE, and deletes do nothing.
                "tableKeys": [{"table": "orders", "keyColumns": ["id"]}],
            },
        }


# A module-scoped async fixture needs a matching event loop scope, otherwise
# pytest-asyncio tears the loop down between tests and the engine's tasks die.
@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def engine_with_postgres(postgres: dict[str, Any]) -> AsyncIterator[Drasi]:
    """One engine for the module.

    Installing the plugin and establishing a replication slot is slow, so the
    engine is shared and each test isolates itself with its own query over its
    own range of row ids.
    """
    engine = await Drasi.create("tier3")
    try:
        await engine.install_plugin("source/postgres")
        await engine.start()
        await engine.add_source("postgres", "db", postgres["config"])
        yield engine
    finally:
        await engine.close()


def execute(dsn: str, statement: str) -> None:
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(statement)


async def watch(engine: Drasi, name: str, row_id: int) -> None:
    """Registers a query scoped to a single row id, and waits for it to run."""
    await engine.add_query(
        name,
        f"MATCH (o:orders) WHERE o.id = {row_id} RETURN o.id AS id, o.status AS status",
        ["db"],
    )
    await wait_for_query_running(engine, name)


async def test_the_plugin_connects_and_the_source_runs(
    engine_with_postgres: Drasi,
) -> None:
    sources = dict(await engine_with_postgres.list_sources())
    assert sources["db"] == "Running"


async def test_an_inserted_row_reaches_the_query(
    engine_with_postgres: Drasi, postgres: dict[str, Any]
) -> None:
    await watch(engine_with_postgres, "inserted", 100)

    execute(postgres["dsn"], "INSERT INTO orders (id, status) VALUES (100, 'open')")

    rows = await wait_for_rows(engine_with_postgres, "inserted", count=1, timeout=60)
    assert rows == [{"id": 100, "status": "open"}]


async def test_an_updated_row_is_reflected(
    engine_with_postgres: Drasi, postgres: dict[str, Any]
) -> None:
    await watch(engine_with_postgres, "updated", 200)

    execute(postgres["dsn"], "INSERT INTO orders (id, status) VALUES (200, 'open')")
    await wait_for_rows(engine_with_postgres, "updated", count=1, timeout=60)

    execute(postgres["dsn"], "UPDATE orders SET status = 'shipped' WHERE id = 200")
    await wait_for_result(
        engine_with_postgres, "updated", [{"id": 200, "status": "shipped"}], timeout=60
    )


async def test_a_deleted_row_is_removed(
    engine_with_postgres: Drasi, postgres: dict[str, Any]
) -> None:
    await watch(engine_with_postgres, "deleted", 300)

    execute(postgres["dsn"], "INSERT INTO orders (id, status) VALUES (300, 'open')")
    await wait_for_rows(engine_with_postgres, "deleted", count=1, timeout=60)

    execute(postgres["dsn"], "DELETE FROM orders WHERE id = 300")
    await wait_for_result(engine_with_postgres, "deleted", [], timeout=60)


async def test_a_python_reaction_receives_database_changes(
    engine_with_postgres: Drasi, postgres: dict[str, Any]
) -> None:
    """A Python callback reacting to real change data capture."""
    await watch(engine_with_postgres, "reacted", 400)
    events = await collect_events(engine_with_postgres, "watcher", ["reacted"])

    execute(postgres["dsn"], "INSERT INTO orders (id, status) VALUES (400, 'open')")

    diffs = await events.take(1, timeout=60)
    assert diffs[0]["type"] == "ADD"
    assert diffs[0]["data"] == {"id": 400, "status": "open"}


async def test_a_query_only_sees_changes_made_after_it_subscribed(
    engine_with_postgres: Drasi, postgres: dict[str, Any]
) -> None:
    """Without a bootstrap provider, pre-existing rows are not replayed.

    This is easy to mistake for a broken connection, so it is pinned here.
    """
    execute(postgres["dsn"], "INSERT INTO orders (id, status) VALUES (500, 'open')")
    await watch(engine_with_postgres, "late", 500)

    assert await engine_with_postgres.get_query_results("late") == []
