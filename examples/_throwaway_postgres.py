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

"""Support code for the Postgres example — not the point of it.

Starts a throwaway Postgres in Docker so the example can stay about Drasi. If
you already have a database, skip all of this and pass your own connection
details to `add_source`.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

MISSING_PACKAGES = """this example needs extra packages:
  make example-postgres
or:
  uv pip install --python .venv/bin/python "testcontainers>=4.15" "psycopg[binary]"
"""

# Row changes only reach the write-ahead log at the `logical` level, which is
# what the Drasi source reads.
LOGICAL_REPLICATION = (
    "postgres -c wal_level=logical -c max_replication_slots=8 -c max_wal_senders=8"
)


@dataclass(frozen=True)
class Postgres:
    """A running database you can point Drasi at."""

    connection: dict[str, Any]
    """Host, port and credentials, shaped for the `postgres` source config."""

    sql: Callable[[str], None]
    """Runs a statement against the database."""


@contextmanager
def throwaway_postgres(schema: str) -> Generator[Postgres]:
    """Starts Postgres in a container, applies `schema`, and cleans up on exit."""
    try:
        import psycopg
        from testcontainers.community.postgres import PostgresContainer
    except ImportError:
        raise SystemExit(MISSING_PACKAGES) from None

    container = PostgresContainer("postgres:16-alpine", driver=None).with_command(
        LOGICAL_REPLICATION
    )

    print("starting postgres (the first run pulls the image)")
    with container as running:
        dsn = (
            f"host={running.get_container_host_ip()} "
            f"port={running.get_exposed_port(5432)} "
            f"dbname={running.dbname} user={running.username} "
            f"password={running.password}"
        )

        def sql(statement: str) -> None:
            with psycopg.connect(dsn, autocommit=True) as connection:
                connection.execute(statement)  # pyright: ignore[reportArgumentType, reportCallIssue]  # psycopg stubs

        sql(schema)

        yield Postgres(
            connection={
                "host": running.get_container_host_ip(),
                # The plugin deserialises this as a u16, so it must be a number.
                "port": int(running.get_exposed_port(5432)),
                "user": running.username,
                "password": running.password,
                "database": running.dbname,
            },
            sql=sql,
        )
