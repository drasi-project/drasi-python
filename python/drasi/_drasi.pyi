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

from collections.abc import Awaitable, Callable, Mapping, Sequence
from types import TracebackType
from typing import Any, Literal, TypedDict

__version__: str
DRASI_CORE_VERSION: str
DRASI_LIB_VERSION: str
DRASI_SDK_VERSION: str
ERROR_CODES: list[str]

QueryLanguage = Literal["cypher", "gql"]
DiffType = Literal["ADD", "UPDATE", "DELETE", "aggregation", "noop"]

class StateStore(TypedDict):
    kind: Literal["redb"]
    path: str

class IndexStore(TypedDict, total=False):
    kind: Literal["rocksdb"]
    path: str
    enable_archive: bool
    direct_io: bool

class Identity(TypedDict, total=False):
    kind: Literal["password", "token"]
    username: str
    password: str
    token: str

class HostInfo(TypedDict):
    """The versions and platform a plugin must match to be loadable."""

    target_triple: str
    arch_suffix: str | None
    ffi_sdk_version: str
    sdk_version: str
    core_version: str
    lib_version: str

class JoinKey(TypedDict):
    label: str
    property: str

class Join(TypedDict):
    id: str
    keys: Sequence[JoinKey]

class SourceChange(TypedDict, total=False):
    """A change pushed into a Python-defined source.

    `op` accepts `add` as a synonym for `insert` and `remove` for `delete`.
    Supplying both `start_id` and `end_id` makes the change a relation rather
    than a node; the Node.js spellings `startId`/`endId` and `inId`/`outId` are
    also accepted.
    """

    op: str
    id: str
    labels: Sequence[str]
    properties: Mapping[str, Any]
    start_id: str
    end_id: str
    effective_from: int

class ResultDiff(TypedDict, total=False):
    type: DiffType
    data: Any
    before: Any
    after: Any
    row_signature: int

class QueryResultEvent(TypedDict):
    query_id: str
    sequence: int
    timestamp: str
    results: list[ResultDiff]
    metadata: dict[str, Any]

class LoadSummary(TypedDict):
    plugins: int
    sources: int
    reactions: int
    bootstrap: int

class PluginKinds(TypedDict):
    sources: list[str]
    reactions: list[str]
    bootstrap: list[str]

class PluginVersion(TypedDict):
    version: str
    platforms: list[str]

class PluginSearchResult(TypedDict):
    reference: str
    full_reference: str
    plugin_type: str
    kind: str
    versions: list[PluginVersion]

class ResolvedPlugin(TypedDict):
    reference: str
    kind: str
    plugin_type: str
    version: str
    target_triple: str
    sdk_version: str
    core_version: str
    lib_version: str

class InstalledPlugin(ResolvedPlugin):
    path: str
    verification: Literal["verified", "unsigned", "tampered"]
    loaded: bool

class ConfigSchema(TypedDict):
    name: str
    schema: dict[str, Any]

# ------------------------------------------------------------------ exceptions

class DrasiError(Exception):
    """Base class for every error raised by Drasi."""

    code: str

class ConfigError(DrasiError): ...
class UnknownKindError(ConfigError): ...
class SourceError(DrasiError): ...
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
    def create(
        id: str,
        *,
        secrets: Mapping[str, str] | None = None,
        state_store: StateStore | None = None,
        index_store: IndexStore | None = None,
        identity: Identity | None = None,
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
        sources: Sequence[str],
        *,
        language: QueryLanguage = "cypher",
        joins: Sequence[Join] | None = None,
    ) -> Awaitable[None]: ...
    def update_query(
        self,
        id: str,
        query: str,
        sources: Sequence[str],
        *,
        language: QueryLanguage = "cypher",
        joins: Sequence[Join] | None = None,
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

    # components provided by plugins
    def add_source(
        self,
        kind: str,
        id: str,
        config: Mapping[str, Any] | None = None,
        *,
        auto_start: bool = True,
    ) -> Awaitable[None]: ...
    def remove_source(self, id: str, *, cleanup: bool = False) -> Awaitable[None]: ...
    def start_source(self, id: str) -> Awaitable[None]: ...
    def stop_source(self, id: str) -> Awaitable[None]: ...
    def list_sources(self) -> Awaitable[list[tuple[str, str]]]: ...
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
    def list_reactions(self) -> Awaitable[list[tuple[str, str]]]: ...

    # plugins
    def load_plugins(
        self, directory: str, verify: Mapping[str, str] | None = None
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
        directory: str | None = None,
        verify: bool = False,
        require_signed: bool = False,
        trusted_identities: Sequence[tuple[str, str]] | None = None,
        load: bool = True,
    ) -> Awaitable[InstalledPlugin]: ...
    def source_config_schema(self, kind: str) -> Awaitable[ConfigSchema]: ...
    def reaction_config_schema(self, kind: str) -> Awaitable[ConfigSchema]: ...
    def bootstrap_config_schema(self, kind: str) -> Awaitable[ConfigSchema]: ...
