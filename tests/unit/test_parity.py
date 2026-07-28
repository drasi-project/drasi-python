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

"""Parity with the Node.js bindings, and with the audit that documents it.

The audit (`docs/api-audit.md`) claims full parity. This keeps that claim
honest: removing a method fails here rather than being noticed by a user.
"""

from __future__ import annotations

import re
from pathlib import Path

import drasi

AUDIT = Path(__file__).resolve().parents[2] / "docs" / "api-audit.md"

# The public surface of @drasi/lib 0.2.0, from its src/drasi.rs and
# test/types.test-d.ts.
NODE_METHODS = """
create fromConfig loadPlugins watchPlugins pluginKinds sourceConfigSchema
reactionConfigSchema bootstrapConfigSchema listPluginTags pullPlugin addSource
addJsSource pushChange updateSource removeSource startSource stopSource
listSources getSourceSchema getGraphSchema addQuery updateQuery removeQuery
startQuery stopQuery getQueryResults listQueries addReaction addJsReaction
addDurableJsReaction updateReaction removeReaction startReaction stopReaction
listReactions getQueryMetrics getReactionMetrics getLifecycleMetrics
onAllEvents onQueryEvents onSourceEvents onReactionEvents onSourceLogs
onQueryLogs onReactionLogs start stop close
""".split()

# Where the binding is language-specific, the name differs by design.
RENAMED = {
    "add_js_source": "add_python_source",
    "add_js_reaction": "add_python_reaction",
    "add_durable_js_reaction": "add_durable_python_reaction",
}


def snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def node_surface() -> set[str]:
    return {RENAMED.get(snake(name), snake(name)) for name in NODE_METHODS}


def python_surface() -> set[str]:
    return {name for name in dir(drasi.Drasi) if not name.startswith("_")} - {"id"}


def test_every_node_method_has_a_python_counterpart() -> None:
    missing = node_surface() - python_surface()
    assert not missing, f"no Python equivalent for {sorted(missing)}"


def test_parity_is_complete() -> None:
    node = node_surface()
    assert len(node & python_surface()) == len(node) == 48


def test_the_audit_still_states_the_real_numbers() -> None:
    """A stale audit is worse than none."""
    audit = AUDIT.read_text(encoding="utf-8")
    shared = len(node_surface() & python_surface())
    extra = len(python_surface() - node_surface())

    assert f"{shared}/{len(node_surface())}" in audit, "the audit's parity figure is stale"
    assert str(extra) in audit, "the audit's count of Python-only methods is stale"


def test_the_python_only_additions_are_present() -> None:
    """The methods the audit calls out as improvements over Node."""
    expected = {
        # streaming, as iterators
        "query_results",
        "query_events",
        "source_events",
        "reaction_events",
        "all_events",
        "query_logs",
        "source_logs",
        "reaction_logs",
        "on_query_results",
        # plugin ergonomics
        "install_plugin",
        "resolve_plugin",
        "search_plugins",
        "write_lockfile",
        "read_lockfile",
        "install_from_lockfile",
        # introspection
        "host_info",
        "get_query_status",
        "get_source_status",
        "get_reaction_status",
        "wait_for_query",
        "is_running",
    }
    assert expected <= python_surface()


def test_the_sync_facade_matches_the_async_surface() -> None:
    from drasi.sync import Drasi as SyncDrasi

    synchronous = {name for name in dir(SyncDrasi) if not name.startswith("_")}
    missing = python_surface() - synchronous
    assert not missing, f"the sync facade is missing {sorted(missing)}"
