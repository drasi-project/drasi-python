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

"""Typed shapes for Drasi's own configuration and results.

These describe the mappings the API accepts and returns. They are `TypedDict`s
rather than dataclasses so plain dicts keep working — nothing here changes what
the API accepts, it only describes it.

Plugin configuration is deliberately absent: those keys belong to the plugin, so
they are passed through untouched. Ask a loaded plugin what it accepts with
``source_config_schema(kind)``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal, TypedDict

__all__ = [
    "ChangeOp",
    "ComponentEvent",
    "ConfigSchema",
    "DiffType",
    "DrasiConfig",
    "GraphSchema",
    "HostInfo",
    "Identity",
    "IndexStore",
    "InstalledPlugin",
    "Join",
    "JoinKey",
    "LifecycleMetrics",
    "LockedPlugin",
    "LogMessage",
    "NodeSchema",
    "PropertySchema",
    "PulledPlugin",
    "QueryConfig",
    "QueryLanguage",
    "QueryMetrics",
    "QueryResultEvent",
    "ReactionConfig",
    "ReactionQueryMetrics",
    "RecoveryPolicy",
    "RelationSchema",
    "ResultDiff",
    "SourceChange",
    "SourceConfig",
    "SourceSchema",
    "StateStore",
]

QueryLanguage = Literal["cypher", "gql"]
"""Query languages the engine understands."""

DiffType = Literal["ADD", "UPDATE", "DELETE", "aggregation", "noop"]
"""How a result row changed."""

ChangeOp = Literal["insert", "add", "update", "delete", "remove"]
"""`add` is a synonym for `insert`, and `remove` for `delete`."""

RecoveryPolicy = Literal["strict", "auto_reset", "skip_gap"]
"""What a durable reaction does when its checkpoint cannot be satisfied."""

DispatchMode = Literal["channel", "broadcast"]


# ------------------------------------------------------------------- creation


class StateStore(TypedDict):
    """Where plugin state and reaction checkpoints are persisted."""

    kind: Literal["redb"]
    path: str


class IndexStore(TypedDict, total=False):
    """Where query indexes are persisted. Needs the `rocksdb` build feature."""

    kind: Literal["rocksdb"]
    path: str
    enable_archive: bool
    direct_io: bool


class Identity(TypedDict, total=False):
    """Credentials handed to plugins that ask for them."""

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


# --------------------------------------------------------------------- changes


class SourceChange(TypedDict, total=False):
    """A change pushed into a Python-defined source.

    Supplying both `start_id` and `end_id` makes this a relation rather than a
    node. The Node.js spellings `startId`/`endId` and `inId`/`outId` are also
    accepted on input.

    Note that `id` is the graph key, not a property: a query selecting `o.id`
    reads a *property* of that name, so emit it in `properties` as well.
    """

    op: ChangeOp
    id: str
    labels: Sequence[str]
    properties: Mapping[str, Any]
    start_id: str
    end_id: str
    effective_from: int


# --------------------------------------------------------------------- queries


class JoinKey(TypedDict):
    label: str
    property: str


class Join(TypedDict):
    id: str
    keys: Sequence[JoinKey]


class ResultDiff(TypedDict, total=False):
    """One way a query's result set changed."""

    type: DiffType
    data: Any
    before: Any
    after: Any
    row_signature: int


class QueryResultEvent(TypedDict):
    """A batch of diffs a query produced."""

    query_id: str
    sequence: int
    timestamp: str
    results: list[ResultDiff]
    metadata: dict[str, Any]


# ------------------------------------------------------------------- streaming


class ComponentEvent(TypedDict, total=False):
    """A lifecycle transition of a component."""

    component_id: str
    component_type: str
    status: str
    timestamp: str
    message: str | None


class LogMessage(TypedDict):
    """A log line emitted by a component, including from a plugin."""

    timestamp: str
    level: str
    message: str
    instance_id: str
    component_id: str
    component_type: str


# --------------------------------------------------------------------- metrics


class QueryMetrics(TypedDict):
    outbox_size: int
    outbox_earliest_seq: int
    outbox_latest_seq: int
    result_seq_advances: int
    live_results_count: int
    outer_transaction_duration_ns_last: int
    outer_transaction_duration_ns_max: int
    snapshot_fetch_count: int


class ReactionQueryMetrics(TypedDict):
    """Per-query metrics for a reaction.

    `checkpoint_sequence` is the forwarder's *delivery* position, so it advances
    even when a durable handler fails. It is not the durable checkpoint.
    """

    checkpoint_sequence: int
    checkpoint_lag: int
    dedup_skip_count: int
    gap_detection_count: int
    recovery_strict_count: int
    recovery_auto_reset_count: int
    recovery_auto_skip_gap_count: int
    fetch_snapshot_count: int
    fetch_outbox_count: int


class LifecycleMetrics(TypedDict):
    startup_rejection_durable_no_store: int
    startup_rejection_durable_on_volatile: int
    startup_rejection_snapshot_skip_gap: int
    startup_rejection_no_snapshot_auto_reset: int
    auto_reset_completions: int
    hash_mismatch_count: int


# ---------------------------------------------------------------------- schema


class PropertySchema(TypedDict, total=False):
    name: str
    data_type: str
    description: str


class NodeSchema(TypedDict):
    label: str
    properties: list[PropertySchema]


class RelationSchema(TypedDict, total=False):
    label: str
    to: str
    properties: list[PropertySchema]


class SourceSchema(TypedDict):
    nodes: list[NodeSchema]
    relations: list[RelationSchema]


class GraphSchema(TypedDict):
    nodes: dict[str, Any]
    relations: dict[str, Any]
    sources_without_schema: list[str]


# --------------------------------------------------------------------- plugins


class ConfigSchema(TypedDict):
    """A plugin's own configuration schema."""

    name: str
    schema: dict[str, Any]


class PulledPlugin(TypedDict):
    reference: str
    path: str
    verification: Literal["verified", "unsigned", "tampered"]


class LockedPlugin(TypedDict):
    """A plugin pinned in `plugins.lock`."""

    reference: str
    version: str
    digest: str
    filename: str
    platform: str
    file_hash: str | None
    sdk_version: str
    core_version: str
    lib_version: str


class InstalledPlugin(TypedDict):
    reference: str
    kind: str
    plugin_type: str
    version: str
    target_triple: str
    sdk_version: str
    core_version: str
    lib_version: str
    path: str
    verification: Literal["verified", "unsigned", "tampered"]
    loaded: bool


# ------------------------------------------------------------ declarative form


class SourceConfig(TypedDict, total=False):
    """A source declared in `from_config`."""

    kind: str
    id: str
    config: Mapping[str, Any]
    auto_start: bool


class QueryConfig(TypedDict, total=False):
    """A query declared in `from_config`."""

    id: str
    query: str
    sources: Sequence[str]
    language: QueryLanguage
    joins: Sequence[Join]


class ReactionConfig(TypedDict, total=False):
    """A reaction declared in `from_config`."""

    kind: str
    id: str
    queries: Sequence[str]
    config: Mapping[str, Any]
    auto_start: bool


class DrasiConfig(TypedDict, total=False):
    """A whole topology, for `Drasi.from_config`."""

    id: str
    secrets: Mapping[str, str]
    state_store: StateStore
    index_store: IndexStore
    identity: Identity
    plugins_dir: str
    sources: Sequence[SourceConfig]
    queries: Sequence[QueryConfig]
    reactions: Sequence[ReactionConfig]
