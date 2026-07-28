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

"""A blocking API, for scripts and notebooks.

The engine is async underneath. This runs an event loop on a background thread
and blocks on each call, which is what you want in a script but not in an
application that already has a loop — use `drasi.Drasi` directly there.

    from drasi.sync import Drasi

    with Drasi.create("my-app") as drasi:
        drasi.start()
        drasi.add_python_source("orders")
        drasi.add_query("open", "MATCH (o:Order) RETURN o.id AS id", ["orders"])
        drasi.push_change("orders", {"op": "insert", "id": "o1", "labels": ["Order"]})
        print(drasi.get_query_results("open"))

Every method mirrors its async counterpart, minus the `await`. Streams become
ordinary iterators, so `for event in drasi.query_results("open")` works.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable, Iterator, Mapping, Sequence
from os import PathLike
from types import TracebackType
from typing import Any, TypeVar

# The facade exists to wrap the extension module, so reaching into it here
# is the point rather than a leak.
from . import _drasi  # pyright: ignore[reportPrivateUsage]
from .types import (
    ComponentEvent,
    ConfigSchema,
    DrasiConfig,
    GraphSchema,
    HostInfo,
    Identity,
    IndexStore,
    InstalledPlugin,
    Join,
    LifecycleMetrics,
    LoadSummary,
    LockedPlugin,
    LogMessage,
    PluginKinds,
    PluginSearchResult,
    PulledPlugin,
    QueryLanguage,
    QueryMetrics,
    QueryResultEvent,
    ReactionQueryMetrics,
    RecoveryPolicy,
    ResolvedPlugin,
    SourceChange,
    SourceSchema,
    StateStore,
)

StrPath = str | PathLike[str]

__all__ = ["Drasi", "Stream"]

T = TypeVar("T")


class _Loop:
    """An asyncio loop on a background thread, shared by every sync engine.

    One loop is enough: the engine's work happens on Rust's own runtime, and
    this only exists to drive the awaitables it hands back.
    """

    _lock = threading.Lock()
    _loop: asyncio.AbstractEventLoop | None = None

    @classmethod
    def get(cls) -> asyncio.AbstractEventLoop:
        with cls._lock:
            if cls._loop is None:
                loop = asyncio.new_event_loop()
                # A daemon thread so a forgotten close cannot hang interpreter
                # exit; resources are still released properly by `close`.
                threading.Thread(
                    target=loop.run_forever,
                    name="drasi-sync",
                    daemon=True,
                ).start()
                cls._loop = loop
            return cls._loop

    @classmethod
    def run(cls, call: Callable[[], Awaitable[T]]) -> T:
        """Invokes `call` **on the background loop** and blocks for its result.

        The awaitable has to be created there rather than here: the engine hands
        back objects bound to whichever loop was running when the method was
        called, so building one on this thread would fail with "no running event
        loop".
        """
        if _running_loop_in_this_thread():
            raise RuntimeError(
                "drasi.sync.Drasi cannot be used from inside a running event loop; "
                "use drasi.Drasi and await it instead"
            )
        return asyncio.run_coroutine_threadsafe(_invoke(call), cls.get()).result()


async def _invoke(call: Callable[[], Awaitable[T]]) -> T:
    return await call()


def _running_loop_in_this_thread() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


class Stream(Iterator[Any]):
    """A blocking iterator over an async :class:`drasi.Stream`."""

    def __init__(self, inner: _drasi.Stream) -> None:
        self._inner = inner

    def __iter__(self) -> Stream:
        return self

    def __next__(self) -> Any:
        try:
            return _Loop.run(lambda: self._inner.__anext__())
        except StopAsyncIteration:
            raise StopIteration from None

    def __repr__(self) -> str:
        return f"sync.{self._inner!r}"


class Drasi:
    """A blocking embedded Drasi engine."""

    def __init__(self, inner: _drasi.Drasi) -> None:
        self._inner = inner

    # ------------------------------------------------------------- lifecycle

    @staticmethod
    def create(
        id: str,
        *,
        secrets: Mapping[str, str] | None = None,
        state_store: StateStore | None = None,
        index_store: IndexStore | None = None,
        identity: Identity | None = None,
    ) -> Drasi:
        return Drasi(
            _Loop.run(
                lambda: _drasi.Drasi.create(
                    id,
                    secrets=secrets,
                    state_store=state_store,
                    index_store=index_store,
                    identity=identity,
                )
            )
        )

    @staticmethod
    def from_config(config: DrasiConfig) -> Drasi:
        """Builds **and starts** an engine from a declarative configuration."""
        return Drasi(_Loop.run(lambda: _drasi.Drasi.from_config(config)))

    @property
    def id(self) -> str:
        return self._inner.id

    def __enter__(self) -> Drasi:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        self.close()
        return False

    def __repr__(self) -> str:
        return f"sync.{self._inner!r}"

    def start(self) -> None:
        _Loop.run(lambda: self._inner.start())

    def stop(self) -> None:
        _Loop.run(lambda: self._inner.stop())

    def close(self) -> None:
        _Loop.run(lambda: self._inner.close())

    def is_running(self) -> bool:
        return _Loop.run(lambda: self._inner.is_running())

    # ---------------------------------------------------------------- queries

    def add_query(
        self,
        id: str,
        query: str,
        sources: Sequence[str],
        *,
        language: QueryLanguage = "cypher",
        joins: Sequence[Join] | None = None,
        **tuning: Any,
    ) -> None:
        _Loop.run(
            lambda: self._inner.add_query(
                id, query, sources, language=language, joins=joins, **tuning
            )
        )

    def update_query(
        self,
        id: str,
        query: str,
        sources: Sequence[str],
        *,
        language: QueryLanguage = "cypher",
        joins: Sequence[Join] | None = None,
        **tuning: Any,
    ) -> None:
        _Loop.run(
            lambda: self._inner.update_query(
                id, query, sources, language=language, joins=joins, **tuning
            )
        )

    def remove_query(self, id: str) -> None:
        _Loop.run(lambda: self._inner.remove_query(id))

    def start_query(self, id: str) -> None:
        _Loop.run(lambda: self._inner.start_query(id))

    def stop_query(self, id: str) -> None:
        _Loop.run(lambda: self._inner.stop_query(id))

    def get_query_results(self, id: str) -> list[dict[str, Any]]:
        return _Loop.run(lambda: self._inner.get_query_results(id))

    def get_query_status(self, id: str) -> str:
        return _Loop.run(lambda: self._inner.get_query_status(id))

    def wait_for_query(self, id: str, *, timeout: float = 30.0) -> None:
        _Loop.run(lambda: self._inner.wait_for_query(id, timeout=timeout))

    def list_queries(self) -> list[tuple[str, str]]:
        return _Loop.run(lambda: self._inner.list_queries())

    # ------------------------------------------- components defined in Python

    def add_python_source(self, id: str, *, auto_start: bool = True) -> None:
        _Loop.run(lambda: self._inner.add_python_source(id, auto_start=auto_start))

    def push_change(self, source_id: str, change: SourceChange) -> None:
        _Loop.run(lambda: self._inner.push_change(source_id, change))

    def add_python_reaction(
        self,
        id: str,
        query_ids: Sequence[str],
        callback: Callable[[QueryResultEvent], object],
    ) -> None:
        _Loop.run(lambda: self._inner.add_python_reaction(id, query_ids, callback))

    def add_durable_python_reaction(
        self,
        id: str,
        query_ids: Sequence[str],
        callback: Callable[[QueryResultEvent], Awaitable[object]],
        *,
        recovery_policy: RecoveryPolicy = "strict",
    ) -> None:
        _Loop.run(
            lambda: self._inner.add_durable_python_reaction(
                id, query_ids, callback, recovery_policy=recovery_policy
            )
        )

    # ----------------------------------------------- plugin-backed components

    def add_source(
        self,
        kind: str,
        id: str,
        config: Mapping[str, Any] | None = None,
        *,
        auto_start: bool = True,
        bootstrap: Mapping[str, Any] | None = None,
    ) -> None:
        _Loop.run(
            lambda: self._inner.add_source(
                kind, id, config, auto_start=auto_start, bootstrap=bootstrap
            )
        )

    def update_source(
        self,
        kind: str,
        id: str,
        config: Mapping[str, Any] | None = None,
        *,
        auto_start: bool = True,
    ) -> None:
        _Loop.run(lambda: self._inner.update_source(kind, id, config, auto_start=auto_start))

    def remove_source(self, id: str, *, cleanup: bool = False) -> None:
        _Loop.run(lambda: self._inner.remove_source(id, cleanup=cleanup))

    def start_source(self, id: str) -> None:
        _Loop.run(lambda: self._inner.start_source(id))

    def stop_source(self, id: str) -> None:
        _Loop.run(lambda: self._inner.stop_source(id))

    def get_source_status(self, id: str) -> str:
        return _Loop.run(lambda: self._inner.get_source_status(id))

    def list_sources(self) -> list[tuple[str, str]]:
        return _Loop.run(lambda: self._inner.list_sources())

    def add_reaction(
        self,
        kind: str,
        id: str,
        query_ids: Sequence[str],
        config: Mapping[str, Any] | None = None,
        *,
        auto_start: bool = True,
    ) -> None:
        _Loop.run(
            lambda: self._inner.add_reaction(kind, id, query_ids, config, auto_start=auto_start)
        )

    def update_reaction(
        self,
        kind: str,
        id: str,
        query_ids: Sequence[str],
        config: Mapping[str, Any] | None = None,
        *,
        auto_start: bool = True,
    ) -> None:
        _Loop.run(
            lambda: self._inner.update_reaction(kind, id, query_ids, config, auto_start=auto_start)
        )

    def remove_reaction(self, id: str, *, cleanup: bool = False) -> None:
        _Loop.run(lambda: self._inner.remove_reaction(id, cleanup=cleanup))

    def start_reaction(self, id: str) -> None:
        _Loop.run(lambda: self._inner.start_reaction(id))

    def stop_reaction(self, id: str) -> None:
        _Loop.run(lambda: self._inner.stop_reaction(id))

    def get_reaction_status(self, id: str) -> str:
        return _Loop.run(lambda: self._inner.get_reaction_status(id))

    def list_reactions(self) -> list[tuple[str, str]]:
        return _Loop.run(lambda: self._inner.list_reactions())

    # -------------------------------------------------------------- streaming

    def query_results(self, query_id: str, *, reaction_id: str | None = None) -> Stream:
        return Stream(
            _Loop.run(lambda: self._inner.query_results(query_id, reaction_id=reaction_id))
        )

    def query_events(self, id: str) -> Stream:
        return Stream(_Loop.run(lambda: self._inner.query_events(id)))

    def source_events(self, id: str) -> Stream:
        return Stream(_Loop.run(lambda: self._inner.source_events(id)))

    def reaction_events(self, id: str) -> Stream:
        return Stream(_Loop.run(lambda: self._inner.reaction_events(id)))

    def all_events(self) -> Stream:
        return Stream(_Loop.run(lambda: self._inner.all_events()))

    def query_logs(self, id: str) -> Stream:
        return Stream(_Loop.run(lambda: self._inner.query_logs(id)))

    def source_logs(self, id: str) -> Stream:
        return Stream(_Loop.run(lambda: self._inner.source_logs(id)))

    def reaction_logs(self, id: str) -> Stream:
        return Stream(_Loop.run(lambda: self._inner.reaction_logs(id)))

    def on_query_results(
        self, query_id: str, callback: Callable[[QueryResultEvent], object]
    ) -> None:
        _Loop.run(lambda: self._inner.on_query_results(query_id, callback))

    def on_query_events(self, id: str, callback: Callable[[ComponentEvent], object]) -> None:
        _Loop.run(lambda: self._inner.on_query_events(id, callback))

    def on_source_events(self, id: str, callback: Callable[[ComponentEvent], object]) -> None:
        _Loop.run(lambda: self._inner.on_source_events(id, callback))

    def on_reaction_events(self, id: str, callback: Callable[[ComponentEvent], object]) -> None:
        _Loop.run(lambda: self._inner.on_reaction_events(id, callback))

    def on_all_events(self, callback: Callable[[ComponentEvent], object]) -> None:
        _Loop.run(lambda: self._inner.on_all_events(callback))

    def on_query_logs(self, id: str, callback: Callable[[LogMessage], object]) -> None:
        _Loop.run(lambda: self._inner.on_query_logs(id, callback))

    def on_source_logs(self, id: str, callback: Callable[[LogMessage], object]) -> None:
        _Loop.run(lambda: self._inner.on_source_logs(id, callback))

    def on_reaction_logs(self, id: str, callback: Callable[[LogMessage], object]) -> None:
        _Loop.run(lambda: self._inner.on_reaction_logs(id, callback))

    # ---------------------------------------------------------------- plugins

    def load_plugins(
        self, directory: StrPath, verify: Mapping[str, str] | None = None
    ) -> LoadSummary:
        return _Loop.run(lambda: self._inner.load_plugins(directory, verify))

    def watch_plugins(self, directory: StrPath, *, debounce_seconds: float = 1.0) -> None:
        _Loop.run(lambda: self._inner.watch_plugins(directory, debounce_seconds=debounce_seconds))

    def plugin_kinds(self) -> PluginKinds:
        return _Loop.run(lambda: self._inner.plugin_kinds())

    def host_info(self) -> HostInfo:
        return self._inner.host_info()

    def search_plugins(self, query: str | None = None) -> list[PluginSearchResult]:
        return _Loop.run(lambda: self._inner.search_plugins(query))

    def list_plugin_tags(self, repository: str) -> list[str]:
        return _Loop.run(lambda: self._inner.list_plugin_tags(repository))

    def resolve_plugin(self, reference: str) -> ResolvedPlugin:
        return _Loop.run(lambda: self._inner.resolve_plugin(reference))

    def install_plugin(
        self,
        reference: str,
        *,
        directory: str | None = None,
        verify: bool = False,
        require_signed: bool = False,
        trusted_identities: Sequence[tuple[str, str]] | None = None,
        load: bool = True,
    ) -> InstalledPlugin:
        return _Loop.run(
            lambda: self._inner.install_plugin(
                reference,
                directory=directory,
                verify=verify,
                require_signed=require_signed,
                trusted_identities=trusted_identities,
                load=load,
            )
        )

    def pull_plugin(
        self,
        reference: str,
        directory: str,
        filename: str,
        *,
        verify: bool = False,
        require_signed: bool = False,
        trusted_identities: Sequence[tuple[str, str]] | None = None,
    ) -> PulledPlugin:
        return _Loop.run(
            lambda: self._inner.pull_plugin(
                reference,
                directory,
                filename,
                verify=verify,
                require_signed=require_signed,
                trusted_identities=trusted_identities,
            )
        )

    def write_lockfile(self, directory: str) -> int:
        return _Loop.run(lambda: self._inner.write_lockfile(directory))

    @staticmethod
    def read_lockfile(directory: str) -> list[LockedPlugin]:
        return _drasi.Drasi.read_lockfile(directory)

    def install_from_lockfile(self, directory: str, *, load: bool = True) -> list[str]:
        return _Loop.run(lambda: self._inner.install_from_lockfile(directory, load=load))

    def source_config_schema(self, kind: str) -> ConfigSchema:
        return _Loop.run(lambda: self._inner.source_config_schema(kind))

    def reaction_config_schema(self, kind: str) -> ConfigSchema:
        return _Loop.run(lambda: self._inner.reaction_config_schema(kind))

    def bootstrap_config_schema(self, kind: str) -> ConfigSchema:
        return _Loop.run(lambda: self._inner.bootstrap_config_schema(kind))

    # ------------------------------------------------------ metrics and schema

    def get_query_metrics(self, id: str) -> QueryMetrics:
        return _Loop.run(lambda: self._inner.get_query_metrics(id))

    def get_reaction_metrics(self, id: str) -> dict[str, ReactionQueryMetrics]:
        return _Loop.run(lambda: self._inner.get_reaction_metrics(id))

    def get_lifecycle_metrics(self) -> LifecycleMetrics:
        return _Loop.run(lambda: self._inner.get_lifecycle_metrics())

    def get_source_schema(self, id: str) -> SourceSchema | None:
        return _Loop.run(lambda: self._inner.get_source_schema(id))

    def get_graph_schema(self) -> GraphSchema:
        return _Loop.run(lambda: self._inner.get_graph_schema())
