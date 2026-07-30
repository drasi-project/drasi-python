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

"""Type stubs for the native extension module."""

import os
from collections.abc import Awaitable, Callable, Mapping, Sequence
from types import TracebackType
from typing import Any, Literal, TypeAlias

from .types import (
    ComponentEvent,
    ConfigSchema,
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
    Middleware,
    PluginKinds,
    PluginSearchResult,
    PulledPlugin,
    QueryMetrics,
    QueryResultEvent,
    ReactionQueryMetrics,
    ResolvedPlugin,
    SourceChange,
    SourceSchema,
    SourceSubscription,
    StateStore,
)

# Directory arguments reach Rust as a PathBuf, which accepts anything
# os.fspath understands, so `Path` is as valid as `str`.
StrPath: TypeAlias = str | os.PathLike[str]

__version__: str
DRASI_CORE_VERSION: str
DRASI_LIB_VERSION: str
DRASI_SDK_VERSION: str
ERROR_CODES: list[str]

QueryLanguage = Literal["cypher", "gql"]
DiffType = Literal["ADD", "UPDATE", "DELETE", "aggregation", "noop"]

class Stream:
    """An async iterator over engine activity.

    Iteration ends when the engine stops producing, so closing the engine
    terminates an open stream rather than leaving it hanging.
    """

    def __aiter__(self) -> Stream: ...
    async def __anext__(self) -> Any: ...
    def __repr__(self) -> str: ...

# ------------------------------------------------------------------ exceptions

class DrasiError(Exception):
    """Base class for every error raised by Drasi."""

    code: str

class ConfigError(DrasiError): ...
class UnknownKindError(ConfigError): ...
class SourceError(DrasiError): ...
class StreamLaggedError(DrasiError): ...
class PluginError(DrasiError): ...
class PluginNotFoundError(PluginError): ...
class PluginCompatibilityError(PluginError): ...
class PluginSignatureError(PluginError): ...

def host_info() -> HostInfo:
    """The versions and platform plugins are matched against."""

class Drasi:
    """An embedded Drasi engine."""

    @property
    def id(self) -> str: ...
    @staticmethod
    def from_config(config: Mapping[str, Any]) -> Awaitable[Drasi]: ...
    @staticmethod
    def create(
        id: str,
        *,
        secrets: Mapping[str, str] | None = None,
        state_store: StateStore | None = None,
        index_store: IndexStore | None = None,
        identity: Identity | None = None,
        plugins_dir: StrPath | None = None,
    ) -> Awaitable[Drasi]: ...
    async def __aenter__(self) -> Drasi: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool: ...

    # lifecycle
    def start(self) -> Awaitable[None]: ...
    def stop(self) -> Awaitable[None]: ...
    def close(self) -> Awaitable[None]: ...
    def is_running(self) -> Awaitable[bool]: ...

    # queries
    def add_query(
        self,
        id: str,
        query: str,
        sources: Sequence[str | SourceSubscription],
        *,
        language: QueryLanguage = "cypher",
        joins: Sequence[Join] | None = None,
        middleware: Sequence[Middleware] | None = None,
        auto_start: bool | None = None,
        enable_bootstrap: bool | None = None,
        bootstrap_timeout_seconds: int | None = None,
        priority_queue_capacity: int | None = None,
        dispatch_buffer_capacity: int | None = None,
        outbox_capacity: int | None = None,
        dispatch_mode: Literal["channel", "broadcast"] | None = None,
    ) -> Awaitable[None]: ...
    def update_query(
        self,
        id: str,
        query: str,
        sources: Sequence[str | SourceSubscription],
        *,
        language: QueryLanguage = "cypher",
        joins: Sequence[Join] | None = None,
        middleware: Sequence[Middleware] | None = None,
        auto_start: bool | None = None,
        enable_bootstrap: bool | None = None,
        bootstrap_timeout_seconds: int | None = None,
        priority_queue_capacity: int | None = None,
        dispatch_buffer_capacity: int | None = None,
        outbox_capacity: int | None = None,
        dispatch_mode: Literal["channel", "broadcast"] | None = None,
    ) -> Awaitable[None]: ...
    def remove_query(self, id: str) -> Awaitable[None]: ...
    def start_query(self, id: str) -> Awaitable[None]: ...
    def stop_query(self, id: str) -> Awaitable[None]: ...
    def get_query_results(self, id: str) -> Awaitable[list[dict[str, Any]]]: ...
    def list_queries(self) -> Awaitable[list[tuple[str, str]]]: ...
    def get_query_status(self, id: str) -> Awaitable[str]: ...
    def wait_for_query(self, id: str, *, timeout: float = 30.0) -> Awaitable[None]: ...

    # components defined in Python
    def add_python_source(self, id: str, *, auto_start: bool = True) -> Awaitable[None]: ...
    def push_change(self, source_id: str, change: SourceChange) -> Awaitable[None]: ...
    def add_python_reaction(
        self,
        id: str,
        query_ids: Sequence[str],
        callback: Callable[[QueryResultEvent], object],
    ) -> Awaitable[None]: ...
    def add_durable_python_reaction(
        self,
        id: str,
        query_ids: Sequence[str],
        callback: Callable[[QueryResultEvent], Awaitable[object]],
        *,
        recovery_policy: Literal["strict", "auto_reset", "skip_gap"] = "strict",
    ) -> Awaitable[None]: ...

    # components provided by plugins
    def add_source(
        self,
        kind: str,
        id: str,
        config: Mapping[str, Any] | None = None,
        *,
        auto_start: bool = True,
        bootstrap: Mapping[str, Any] | None = None,
    ) -> Awaitable[None]: ...
    def remove_source(self, id: str, *, cleanup: bool = False) -> Awaitable[None]: ...
    def start_source(self, id: str) -> Awaitable[None]: ...
    def stop_source(self, id: str) -> Awaitable[None]: ...
    def get_source_status(self, id: str) -> Awaitable[str]: ...
    def list_sources(self) -> Awaitable[list[tuple[str, str]]]: ...
    def update_source(
        self,
        kind: str,
        id: str,
        config: Mapping[str, Any] | None = None,
        *,
        auto_start: bool = True,
    ) -> Awaitable[None]: ...
    def add_reaction(
        self,
        kind: str,
        id: str,
        query_ids: Sequence[str],
        config: Mapping[str, Any] | None = None,
        *,
        auto_start: bool = True,
    ) -> Awaitable[None]: ...
    def remove_reaction(self, id: str, *, cleanup: bool = False) -> Awaitable[None]: ...
    def start_reaction(self, id: str) -> Awaitable[None]: ...
    def stop_reaction(self, id: str) -> Awaitable[None]: ...
    def get_reaction_status(self, id: str) -> Awaitable[str]: ...
    def list_reactions(self) -> Awaitable[list[tuple[str, str]]]: ...
    def update_reaction(
        self,
        kind: str,
        id: str,
        query_ids: Sequence[str],
        config: Mapping[str, Any] | None = None,
        *,
        auto_start: bool = True,
    ) -> Awaitable[None]: ...

    # metrics and schema
    def get_query_metrics(self, id: str) -> Awaitable[QueryMetrics]: ...
    def get_reaction_metrics(self, id: str) -> Awaitable[dict[str, ReactionQueryMetrics]]: ...
    def get_lifecycle_metrics(self) -> Awaitable[LifecycleMetrics]: ...
    def get_source_schema(self, id: str) -> Awaitable[SourceSchema | None]: ...
    def get_graph_schema(self) -> Awaitable[GraphSchema]: ...

    # streaming
    def query_results(
        self, query_id: str, *, reaction_id: str | None = None
    ) -> Awaitable[Stream]: ...
    def query_events(self, id: str) -> Awaitable[Stream]: ...
    def source_events(self, id: str) -> Awaitable[Stream]: ...
    def reaction_events(self, id: str) -> Awaitable[Stream]: ...
    def all_events(self) -> Awaitable[Stream]: ...
    def query_logs(self, id: str) -> Awaitable[Stream]: ...
    def source_logs(self, id: str) -> Awaitable[Stream]: ...
    def reaction_logs(self, id: str) -> Awaitable[Stream]: ...
    def on_query_results(
        self, query_id: str, callback: Callable[[QueryResultEvent], object]
    ) -> Awaitable[None]: ...
    def on_query_events(
        self, id: str, callback: Callable[[ComponentEvent], object]
    ) -> Awaitable[None]: ...
    def on_source_events(
        self, id: str, callback: Callable[[ComponentEvent], object]
    ) -> Awaitable[None]: ...
    def on_reaction_events(
        self, id: str, callback: Callable[[ComponentEvent], object]
    ) -> Awaitable[None]: ...
    def on_all_events(self, callback: Callable[[ComponentEvent], object]) -> Awaitable[None]: ...
    def on_query_logs(
        self, id: str, callback: Callable[[LogMessage], object]
    ) -> Awaitable[None]: ...
    def on_source_logs(
        self, id: str, callback: Callable[[LogMessage], object]
    ) -> Awaitable[None]: ...
    def on_reaction_logs(
        self, id: str, callback: Callable[[LogMessage], object]
    ) -> Awaitable[None]: ...

    # plugins
    def load_plugins(
        self, directory: StrPath, verify: Mapping[str, str] | None = None
    ) -> Awaitable[LoadSummary]: ...
    def plugin_kinds(self) -> Awaitable[PluginKinds]: ...
    def host_info(self) -> HostInfo: ...
    def search_plugins(self, query: str | None = None) -> Awaitable[list[PluginSearchResult]]: ...
    def list_plugin_tags(self, repository: str) -> Awaitable[list[str]]: ...
    def resolve_plugin(self, reference: str) -> Awaitable[ResolvedPlugin]: ...
    def install_plugin(
        self,
        reference: str,
        *,
        directory: StrPath | None = None,
        verify: bool = False,
        require_signed: bool = False,
        trusted_identities: Sequence[tuple[str, str]] | None = None,
        load: bool = True,
    ) -> Awaitable[InstalledPlugin]: ...
    def watch_plugins(
        self, directory: StrPath, *, debounce_seconds: float = 1.0
    ) -> Awaitable[None]: ...
    def pull_plugin(
        self,
        reference: str,
        directory: StrPath,
        filename: str,
        *,
        verify: bool = False,
        require_signed: bool = False,
        trusted_identities: Sequence[tuple[str, str]] | None = None,
    ) -> Awaitable[PulledPlugin]: ...
    def write_lockfile(self, directory: StrPath) -> Awaitable[int]: ...
    @staticmethod
    def read_lockfile(directory: StrPath) -> list[LockedPlugin]: ...
    def install_from_lockfile(
        self, directory: str, *, load: bool = True
    ) -> Awaitable[list[str]]: ...
    def source_config_schema(self, kind: str) -> Awaitable[ConfigSchema]: ...
    def reaction_config_schema(self, kind: str) -> Awaitable[ConfigSchema]: ...
    def bootstrap_config_schema(self, kind: str) -> Awaitable[ConfigSchema]: ...
    def secret_store_config_schema(self, kind: str) -> Awaitable[ConfigSchema]: ...
    def use_secret_store(
        self, kind: str, config: Mapping[str, Any] | None = None
    ) -> Awaitable[None]: ...
