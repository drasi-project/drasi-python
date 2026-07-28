// Copyright 2026 The Drasi Authors.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

//! The `Drasi` engine handle exposed to Python.

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Duration;

use drasi_lib::api::Query;
use drasi_lib::config::{QueryJoinConfig, QueryJoinKeyConfig};
use drasi_lib::{ComponentStatus, DrasiLib};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyString};
use pyo3_async_runtimes::tokio::future_into_py;
use tokio::sync::Mutex;

use crate::components::{
    BoxedReaction, BoxedSource, PythonReaction, PythonSource, SharedSource, StreamingReaction,
};
use crate::conversions::{json_to_py, json_to_py_snake, py_to_json, source_change_from_py};
use crate::errors::{engine_error, error, DrasiErrorCode};
use crate::plugins::{self, LoadSummary, PluginHost, Resolved};
use crate::stores::CreateOptions;
use crate::streams::{self, Stream};

/// Shared engine state.
///
/// Held behind an `Arc` so every async method can clone a handle into a
/// `Send + 'static` future without borrowing `self` across an await point.
pub struct Inner {
    pub id: String,
    pub core: DrasiLib,
    /// Python-defined sources, kept so `push_change` can reach them directly.
    pub python_sources: Mutex<HashMap<String, Arc<PythonSource>>>,
    pub plugins: Arc<PluginHost>,
    /// Directory `install_plugin` writes to when the caller does not pick one.
    default_plugin_dir: Mutex<Option<PathBuf>>,
    /// Distinguishes the reactions created to back result streams.
    stream_counter: AtomicU64,
}

impl Inner {
    fn next_stream_id(&self) -> u64 {
        self.stream_counter.fetch_add(1, Ordering::Relaxed)
    }

    /// A per-engine directory for downloaded plugins.
    ///
    /// Downloads are kept out of the working directory, and separated per
    /// engine so concurrent instances cannot overwrite each other's binaries.
    async fn default_plugin_dir(&self) -> std::io::Result<PathBuf> {
        let mut guard = self.default_plugin_dir.lock().await;
        if let Some(existing) = guard.as_ref() {
            return Ok(existing.clone());
        }
        let directory = std::env::temp_dir()
            .join("drasi-python-plugins")
            .join(sanitize(&self.id));
        std::fs::create_dir_all(&directory)?;
        *guard = Some(directory.clone());
        Ok(directory)
    }
}

/// Makes an engine id safe to use as a single path component.
fn sanitize(id: &str) -> String {
    id.chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || c == '-' || c == '_' {
                c
            } else {
                '_'
            }
        })
        .collect()
}

/// An embedded Drasi engine.
#[pyclass(module = "drasi._drasi", name = "Drasi", frozen)]
pub struct Drasi {
    inner: Arc<Inner>,
}

impl Drasi {
    fn inner(&self) -> Arc<Inner> {
        Arc::clone(&self.inner)
    }
}

#[pymethods]
impl Drasi {
    /// Builds an engine. Await the result to obtain the `Drasi` instance.
    ///
    /// The optional stores are all in-memory unless configured: `secrets` seeds
    /// the store plugins resolve `ConfigValue::Secret` against, `state_store`
    /// persists plugin state, `index_store` persists query indexes, and
    /// `identity` supplies credentials to plugins that ask for them.
    #[staticmethod]
    #[pyo3(signature = (id, *, secrets = None, state_store = None, index_store = None, identity = None))]
    fn create<'py>(
        py: Python<'py>,
        id: String,
        secrets: Option<HashMap<String, String>>,
        state_store: Option<&Bound<'py, PyAny>>,
        index_store: Option<&Bound<'py, PyAny>>,
        identity: Option<&Bound<'py, PyAny>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        // Parse eagerly so a malformed option raises before the caller awaits.
        let options = CreateOptions::parse(secrets, state_store, index_store, identity)?;

        future_into_py(py, async move {
            let (builder, secrets) = options
                .apply(DrasiLib::builder().with_id(id.clone()))
                .await?;
            let core = builder.build().await.map_err(engine_error)?;
            Ok(Drasi {
                inner: Arc::new(Inner {
                    id,
                    core,
                    python_sources: Mutex::new(HashMap::new()),
                    plugins: Arc::new(PluginHost::new(secrets)),
                    default_plugin_dir: Mutex::new(None),
                    stream_counter: AtomicU64::new(0),
                }),
            })
        })
    }

    /// The engine identifier supplied to `create`.
    #[getter]
    fn id(&self) -> &str {
        &self.inner.id
    }

    /// Starts the engine and every component that is configured to auto-start.
    fn start<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(
            py,
            async move { inner.core.start().await.map_err(engine_error) },
        )
    }

    /// Stops the engine, leaving its components in place.
    fn stop<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(
            py,
            async move { inner.core.stop().await.map_err(engine_error) },
        )
    }

    /// Stops the engine and releases all of its resources.
    fn close<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            inner.core.shutdown().await.map_err(engine_error)
        })
    }

    /// Whether the engine is currently running.
    fn is_running<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move { Ok(inner.core.is_running().await) })
    }

    fn __aenter__<'py>(slf: PyRef<'py, Self>, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let handle: Py<Drasi> = slf.into();
        future_into_py(py, async move { Ok(handle) })
    }

    #[pyo3(signature = (*_args))]
    fn __aexit__<'py>(
        &self,
        py: Python<'py>,
        _args: &Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            inner.core.shutdown().await.map_err(engine_error)?;
            Ok(false)
        })
    }

    fn __repr__(&self, py: Python<'_>) -> PyResult<String> {
        let id = PyString::new(py, &self.inner.id).repr()?;
        Ok(format!("Drasi(id={id})"))
    }

    // ---------------------------------------------------------------- queries

    /// Registers a continuous query over one or more sources.
    #[pyo3(signature = (
        id, query, sources, *, language = "cypher", joins = None,
        auto_start = None, enable_bootstrap = None, bootstrap_timeout_seconds = None,
        priority_queue_capacity = None, dispatch_buffer_capacity = None,
        outbox_capacity = None, dispatch_mode = None,
    ))]
    #[allow(clippy::too_many_arguments)]
    fn add_query<'py>(
        &self,
        py: Python<'py>,
        id: String,
        query: String,
        sources: Vec<String>,
        language: &str,
        joins: Option<&Bound<'py, PyAny>>,
        auto_start: Option<bool>,
        enable_bootstrap: Option<bool>,
        bootstrap_timeout_seconds: Option<u64>,
        priority_queue_capacity: Option<usize>,
        dispatch_buffer_capacity: Option<usize>,
        outbox_capacity: Option<usize>,
        dispatch_mode: Option<String>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let config = build_query(
            &id,
            &query,
            &sources,
            language,
            joins,
            QueryTuning {
                auto_start,
                enable_bootstrap,
                bootstrap_timeout_seconds,
                priority_queue_capacity,
                dispatch_buffer_capacity,
                outbox_capacity,
                dispatch_mode,
            },
        )?;
        let inner = self.inner();
        future_into_py(py, async move {
            inner.core.add_query(config).await.map_err(engine_error)
        })
    }

    /// Replaces the definition of an existing query.
    #[pyo3(signature = (
        id, query, sources, *, language = "cypher", joins = None,
        auto_start = None, enable_bootstrap = None, bootstrap_timeout_seconds = None,
        priority_queue_capacity = None, dispatch_buffer_capacity = None,
        outbox_capacity = None, dispatch_mode = None,
    ))]
    #[allow(clippy::too_many_arguments)]
    fn update_query<'py>(
        &self,
        py: Python<'py>,
        id: String,
        query: String,
        sources: Vec<String>,
        language: &str,
        joins: Option<&Bound<'py, PyAny>>,
        auto_start: Option<bool>,
        enable_bootstrap: Option<bool>,
        bootstrap_timeout_seconds: Option<u64>,
        priority_queue_capacity: Option<usize>,
        dispatch_buffer_capacity: Option<usize>,
        outbox_capacity: Option<usize>,
        dispatch_mode: Option<String>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let config = build_query(
            &id,
            &query,
            &sources,
            language,
            joins,
            QueryTuning {
                auto_start,
                enable_bootstrap,
                bootstrap_timeout_seconds,
                priority_queue_capacity,
                dispatch_buffer_capacity,
                outbox_capacity,
                dispatch_mode,
            },
        )?;
        let inner = self.inner();
        future_into_py(py, async move {
            inner
                .core
                .update_query(&id, config)
                .await
                .map_err(engine_error)
        })
    }

    fn remove_query<'py>(&self, py: Python<'py>, id: String) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            inner.core.remove_query(&id).await.map_err(engine_error)
        })
    }

    fn start_query<'py>(&self, py: Python<'py>, id: String) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            inner.core.start_query(&id).await.map_err(engine_error)
        })
    }

    fn stop_query<'py>(&self, py: Python<'py>, id: String) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            inner.core.stop_query(&id).await.map_err(engine_error)
        })
    }

    /// The current result set of a query, as a list of row dicts.
    fn get_query_results<'py>(&self, py: Python<'py>, id: String) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            let rows = inner
                .core
                .get_query_results(&id)
                .await
                .map_err(engine_error)?;
            Python::attach(|py| {
                let converted: PyResult<Vec<Py<PyAny>>> = rows
                    .iter()
                    .map(|row| json_to_py(py, row).map(|value| value.unbind()))
                    .collect();
                converted
            })
        })
    }

    /// The current status of a query, such as `"Running"`.
    fn get_query_status<'py>(&self, py: Python<'py>, id: String) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            inner
                .core
                .get_query_status(&id)
                .await
                .map(|status| format!("{status:?}"))
                .map_err(engine_error)
        })
    }

    /// Waits until a query is running.
    ///
    /// `add_query` returns once the query is provisioned; it finishes starting
    /// in the background, so reading results immediately can fail with "is not
    /// running". Await this first when you need to read straight away.
    #[pyo3(signature = (id, *, timeout = 30.0))]
    fn wait_for_query<'py>(
        &self,
        py: Python<'py>,
        id: String,
        timeout: f64,
    ) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            let deadline = tokio::time::Instant::now() + Duration::from_secs_f64(timeout.max(0.0));
            let mut last = String::from("unknown");
            while tokio::time::Instant::now() < deadline {
                match inner.core.get_query_status(&id).await {
                    Ok(ComponentStatus::Running) => return Ok(()),
                    Ok(ComponentStatus::Error) => {
                        return Err(engine_error(format!("query '{id}' failed to start")))
                    }
                    Ok(status) => last = format!("{status:?}"),
                    // The query may not be registered in the graph yet.
                    Err(err) => last = err.to_string(),
                }
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
            Err(engine_error(format!(
                "query '{id}' was still {last} after {timeout}s"
            )))
        })
    }

    /// Every registered query, as `(id, status)` pairs.
    fn list_queries<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            let queries = inner.core.list_queries().await.map_err(engine_error)?;
            Ok(queries
                .into_iter()
                .map(|(id, status)| (id, format!("{status:?}")))
                .collect::<Vec<_>>())
        })
    }

    // ------------------------------------------------------ metrics and schema

    /// Output metrics for a query.
    fn get_query_metrics<'py>(&self, py: Python<'py>, id: String) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            let m = inner
                .core
                .get_query_output_metrics(&id)
                .await
                .map_err(engine_error)?;
            Python::attach(|py| {
                let out = PyDict::new(py);
                out.set_item("outbox_size", m.outbox_size)?;
                out.set_item("outbox_earliest_seq", m.outbox_earliest_seq)?;
                out.set_item("outbox_latest_seq", m.outbox_latest_seq)?;
                out.set_item("result_seq_advances", m.result_seq_advances)?;
                out.set_item("live_results_count", m.live_results_count)?;
                out.set_item(
                    "outer_transaction_duration_ns_last",
                    m.outer_transaction_duration_ns_last,
                )?;
                out.set_item(
                    "outer_transaction_duration_ns_max",
                    m.outer_transaction_duration_ns_max,
                )?;
                out.set_item("snapshot_fetch_count", m.snapshot_fetch_count)?;
                Ok(out.unbind())
            })
        })
    }

    /// Metrics for a reaction, keyed by the query they relate to.
    fn get_reaction_metrics<'py>(
        &self,
        py: Python<'py>,
        id: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            let metrics = inner
                .core
                .get_reaction_metrics(&id)
                .await
                .map_err(engine_error)?;
            Python::attach(|py| {
                let out = PyDict::new(py);
                for (query_id, m) in metrics {
                    let entry = PyDict::new(py);
                    entry.set_item("checkpoint_sequence", m.checkpoint_sequence)?;
                    entry.set_item("checkpoint_lag", m.checkpoint_lag)?;
                    entry.set_item("dedup_skip_count", m.dedup_skip_count)?;
                    entry.set_item("gap_detection_count", m.gap_detection_count)?;
                    entry.set_item("recovery_strict_count", m.recovery_strict_count)?;
                    entry.set_item("recovery_auto_reset_count", m.recovery_auto_reset_count)?;
                    entry.set_item(
                        "recovery_auto_skip_gap_count",
                        m.recovery_auto_skip_gap_count,
                    )?;
                    entry.set_item("fetch_snapshot_count", m.fetch_snapshot_count)?;
                    entry.set_item("fetch_outbox_count", m.fetch_outbox_count)?;
                    out.set_item(query_id, entry)?;
                }
                Ok(out.unbind())
            })
        })
    }

    /// Engine-wide lifecycle metrics, mostly about durable-reaction recovery.
    fn get_lifecycle_metrics<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            let m = inner
                .core
                .get_lifecycle_metrics()
                .await
                .map_err(engine_error)?;
            Python::attach(|py| {
                let out = PyDict::new(py);
                out.set_item(
                    "startup_rejection_durable_no_store",
                    m.startup_rejection_durable_no_store,
                )?;
                out.set_item(
                    "startup_rejection_durable_on_volatile",
                    m.startup_rejection_durable_on_volatile,
                )?;
                out.set_item(
                    "startup_rejection_snapshot_skip_gap",
                    m.startup_rejection_snapshot_skip_gap,
                )?;
                out.set_item(
                    "startup_rejection_no_snapshot_auto_reset",
                    m.startup_rejection_no_snapshot_auto_reset,
                )?;
                out.set_item("auto_reset_completions", m.auto_reset_completions)?;
                out.set_item("hash_mismatch_count", m.hash_mismatch_count)?;
                Ok(out.unbind())
            })
        })
    }

    /// The graph shape a source reports, if it describes one.
    fn get_source_schema<'py>(&self, py: Python<'py>, id: String) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            let schema = inner
                .core
                .get_source_schema(&id)
                .await
                .map_err(engine_error)?;
            Python::attach(|py| match schema {
                Some(schema) => {
                    let value = serde_json::to_value(schema).map_err(engine_error)?;
                    Ok(json_to_py_snake(py, &value)?.unbind())
                }
                None => Ok(py.None()),
            })
        })
    }

    /// The combined graph shape across every source.
    fn get_graph_schema<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            let schema = inner.core.get_graph_schema().await.map_err(engine_error)?;
            let value = serde_json::to_value(schema).map_err(engine_error)?;
            Python::attach(|py| Ok(json_to_py_snake(py, &value)?.unbind()))
        })
    }

    // -------------------------------------------------------------- streaming

    /// Streams the diffs a query produces.
    ///
    /// This is what most callers want: `async for event in drasi.query_results(id)`.
    /// Result diffs reach subscribers through a reaction, so this registers one
    /// behind the scenes; it is removed when the engine closes.
    #[pyo3(signature = (query_id, *, reaction_id = None))]
    fn query_results<'py>(
        &self,
        py: Python<'py>,
        query_id: String,
        reaction_id: Option<String>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            let id = reaction_id
                .unwrap_or_else(|| format!("__stream_{query_id}_{}", inner.next_stream_id()));
            let (receiver, sender) = streams::channel();
            inner
                .core
                .add_reaction(StreamingReaction::new(&id, vec![query_id.clone()], sender))
                .await
                .map_err(engine_error)?;
            Ok(Stream::new(
                receiver,
                format!("results of query '{query_id}'"),
            ))
        })
    }

    /// Streams lifecycle events for a query, replaying its history first.
    fn query_events<'py>(&self, py: Python<'py>, id: String) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            let (history, receiver) = inner
                .core
                .subscribe_query_events(&id)
                .await
                .map_err(engine_error)?;
            Ok(broadcast_stream(
                format!("events of query '{id}'"),
                history,
                receiver,
            ))
        })
    }

    /// Streams lifecycle events for a source, replaying its history first.
    fn source_events<'py>(&self, py: Python<'py>, id: String) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            let (history, receiver) = inner
                .core
                .subscribe_source_events(&id)
                .await
                .map_err(engine_error)?;
            Ok(broadcast_stream(
                format!("events of source '{id}'"),
                history,
                receiver,
            ))
        })
    }

    /// Streams lifecycle events for a reaction, replaying its history first.
    fn reaction_events<'py>(&self, py: Python<'py>, id: String) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            let (history, receiver) = inner
                .core
                .subscribe_reaction_events(&id)
                .await
                .map_err(engine_error)?;
            Ok(broadcast_stream(
                format!("events of reaction '{id}'"),
                history,
                receiver,
            ))
        })
    }

    /// Streams lifecycle events for every component.
    fn all_events<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            let events = inner.core.get_all_events().await.map_err(engine_error)?;
            let (receiver, sender) = streams::channel();
            streams::pump_stream(events, sender);
            Ok(Stream::new(receiver, "events of every component"))
        })
    }

    /// Streams log lines emitted by a query, replaying its history first.
    fn query_logs<'py>(&self, py: Python<'py>, id: String) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            let (history, receiver) = inner
                .core
                .subscribe_query_logs(&id)
                .await
                .map_err(engine_error)?;
            Ok(broadcast_stream(
                format!("logs of query '{id}'"),
                history,
                receiver,
            ))
        })
    }

    /// Streams log lines emitted by a source, replaying its history first.
    fn source_logs<'py>(&self, py: Python<'py>, id: String) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            let (history, receiver) = inner
                .core
                .subscribe_source_logs(&id)
                .await
                .map_err(engine_error)?;
            Ok(broadcast_stream(
                format!("logs of source '{id}'"),
                history,
                receiver,
            ))
        })
    }

    /// Streams log lines emitted by a reaction, replaying its history first.
    fn reaction_logs<'py>(&self, py: Python<'py>, id: String) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            let (history, receiver) = inner
                .core
                .subscribe_reaction_logs(&id)
                .await
                .map_err(engine_error)?;
            Ok(broadcast_stream(
                format!("logs of reaction '{id}'"),
                history,
                receiver,
            ))
        })
    }

    /// Calls `callback` with each item. The `query_events` iterator is usually nicer.
    fn on_query_events<'py>(
        &self,
        py: Python<'py>,
        id: String,
        callback: Py<PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        require_callable(py, &callback)?;
        let inner = self.inner();
        future_into_py(py, async move {
            let (history, receiver) = inner
                .core
                .subscribe_query_events(&id)
                .await
                .map_err(engine_error)?;
            let description = format!("events of query '{id}'");
            let (rx, sender) = streams::channel();
            streams::pump_broadcast(history, receiver, sender);
            streams::pump_callback(rx, callback, description);
            Ok(())
        })
    }
    /// Calls `callback` with each item. The `source_events` iterator is usually nicer.
    fn on_source_events<'py>(
        &self,
        py: Python<'py>,
        id: String,
        callback: Py<PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        require_callable(py, &callback)?;
        let inner = self.inner();
        future_into_py(py, async move {
            let (history, receiver) = inner
                .core
                .subscribe_source_events(&id)
                .await
                .map_err(engine_error)?;
            let description = format!("events of source '{id}'");
            let (rx, sender) = streams::channel();
            streams::pump_broadcast(history, receiver, sender);
            streams::pump_callback(rx, callback, description);
            Ok(())
        })
    }
    /// Calls `callback` with each item. The `reaction_events` iterator is usually nicer.
    fn on_reaction_events<'py>(
        &self,
        py: Python<'py>,
        id: String,
        callback: Py<PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        require_callable(py, &callback)?;
        let inner = self.inner();
        future_into_py(py, async move {
            let (history, receiver) = inner
                .core
                .subscribe_reaction_events(&id)
                .await
                .map_err(engine_error)?;
            let description = format!("events of reaction '{id}'");
            let (rx, sender) = streams::channel();
            streams::pump_broadcast(history, receiver, sender);
            streams::pump_callback(rx, callback, description);
            Ok(())
        })
    }
    /// Calls `callback` with each item. The `query_logs` iterator is usually nicer.
    fn on_query_logs<'py>(
        &self,
        py: Python<'py>,
        id: String,
        callback: Py<PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        require_callable(py, &callback)?;
        let inner = self.inner();
        future_into_py(py, async move {
            let (history, receiver) = inner
                .core
                .subscribe_query_logs(&id)
                .await
                .map_err(engine_error)?;
            let description = format!("logs of query '{id}'");
            let (rx, sender) = streams::channel();
            streams::pump_broadcast(history, receiver, sender);
            streams::pump_callback(rx, callback, description);
            Ok(())
        })
    }
    /// Calls `callback` with each item. The `source_logs` iterator is usually nicer.
    fn on_source_logs<'py>(
        &self,
        py: Python<'py>,
        id: String,
        callback: Py<PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        require_callable(py, &callback)?;
        let inner = self.inner();
        future_into_py(py, async move {
            let (history, receiver) = inner
                .core
                .subscribe_source_logs(&id)
                .await
                .map_err(engine_error)?;
            let description = format!("logs of source '{id}'");
            let (rx, sender) = streams::channel();
            streams::pump_broadcast(history, receiver, sender);
            streams::pump_callback(rx, callback, description);
            Ok(())
        })
    }
    /// Calls `callback` with each item. The `reaction_logs` iterator is usually nicer.
    fn on_reaction_logs<'py>(
        &self,
        py: Python<'py>,
        id: String,
        callback: Py<PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        require_callable(py, &callback)?;
        let inner = self.inner();
        future_into_py(py, async move {
            let (history, receiver) = inner
                .core
                .subscribe_reaction_logs(&id)
                .await
                .map_err(engine_error)?;
            let description = format!("logs of reaction '{id}'");
            let (rx, sender) = streams::channel();
            streams::pump_broadcast(history, receiver, sender);
            streams::pump_callback(rx, callback, description);
            Ok(())
        })
    }
    /// Calls `callback` with every component's lifecycle events.
    fn on_all_events<'py>(
        &self,
        py: Python<'py>,
        callback: Py<PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        require_callable(py, &callback)?;
        let inner = self.inner();
        future_into_py(py, async move {
            let events = inner.core.get_all_events().await.map_err(engine_error)?;
            let (rx, sender) = streams::channel();
            streams::pump_stream(events, sender);
            streams::pump_callback(rx, callback, "events of every component".to_string());
            Ok(())
        })
    }

    /// Calls `callback` with each diff a query produces.
    ///
    /// The `query_results(id)` iterator is usually nicer; this exists for
    /// parity with the Node.js binding.
    fn on_query_results<'py>(
        &self,
        py: Python<'py>,
        query_id: String,
        callback: Py<PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        require_callable(py, &callback)?;
        let inner = self.inner();
        future_into_py(py, async move {
            let reaction_id = format!("__stream_{query_id}_{}", inner.next_stream_id());
            let description = format!("results of query '{query_id}'");
            let (rx, sender) = streams::channel();
            inner
                .core
                .add_reaction(StreamingReaction::new(&reaction_id, vec![query_id], sender))
                .await
                .map_err(engine_error)?;
            streams::pump_callback(rx, callback, description);
            Ok(())
        })
    }

    // ---------------------------------------------------------------- plugins

    /// Discovers and loads every plugin in `directory`.
    ///
    /// `verify` maps a file name to its expected SHA-256. When supplied it acts
    /// as an allowlist: files that are absent from the map, or whose hash does
    /// not match, are skipped.
    #[pyo3(signature = (directory, verify = None))]
    fn load_plugins<'py>(
        &self,
        py: Python<'py>,
        directory: PathBuf,
        verify: Option<HashMap<String, String>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            let summary = inner
                .plugins
                .load_dir(&inner.core, &inner.id, &directory, verify.as_ref())
                .await
                .map_err(plugin_error)?;
            Python::attach(|py| summary_to_py(py, summary).map(Bound::unbind))
        })
    }

    /// Watches a directory and loads plugins as they appear.
    ///
    /// Returns once watching has started. A loaded cdylib cannot be safely
    /// unloaded, so removing a file leaves its kinds registered.
    #[pyo3(signature = (directory, *, debounce_seconds = 1.0))]
    fn watch_plugins<'py>(
        &self,
        py: Python<'py>,
        directory: PathBuf,
        debounce_seconds: f64,
    ) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            let plugins = Arc::clone(&inner.plugins);
            plugins
                .watch(
                    inner.core.clone(),
                    inner.id.clone(),
                    directory,
                    Duration::from_secs_f64(debounce_seconds.max(0.0)),
                )
                .await
                .map_err(plugin_error)
        })
    }

    /// The plugin kinds currently registered, grouped by component type.
    fn plugin_kinds<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            let sources = inner.plugins.source_kinds().await;
            let reactions = inner.plugins.reaction_kinds().await;
            let bootstrap = inner.plugins.bootstrap_kinds().await;
            Python::attach(|py| {
                let kinds = PyDict::new(py);
                kinds.set_item("sources", sources)?;
                kinds.set_item("reactions", reactions)?;
                kinds.set_item("bootstrap", bootstrap)?;
                Ok(kinds.unbind())
            })
        })
    }

    /// The version and platform information plugins are matched against.
    fn host_info<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        json_to_py(py, &plugins::describe_host())
    }

    /// Every plugin published to the registry, from its directory index.
    #[pyo3(signature = (query = None))]
    fn search_plugins<'py>(
        &self,
        py: Python<'py>,
        query: Option<String>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let query = query.unwrap_or_default();
        future_into_py(py, async move {
            let client = plugins::registry_client(Vec::new(), false);
            let found = client.search_plugins(&query).await.map_err(plugin_error)?;
            Python::attach(|py| {
                let results = PyList::empty(py);
                for entry in found {
                    let item = PyDict::new(py);
                    item.set_item("reference", &entry.reference)?;
                    item.set_item("full_reference", &entry.full_reference)?;
                    let (plugin_type, kind) = entry
                        .reference
                        .split_once('/')
                        .unwrap_or(("", entry.reference.as_str()));
                    item.set_item("plugin_type", plugin_type)?;
                    item.set_item("kind", kind)?;
                    let versions = PyList::empty(py);
                    for version in &entry.versions {
                        let info = PyDict::new(py);
                        info.set_item("version", &version.version)?;
                        info.set_item("platforms", version.platforms.clone())?;
                        versions.append(info)?;
                    }
                    item.set_item("versions", versions)?;
                    results.append(item)?;
                }
                Ok(results.unbind())
            })
        })
    }

    /// Every tag published for a plugin repository, such as `source/postgres`.
    fn list_plugin_tags<'py>(
        &self,
        py: Python<'py>,
        repository: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        future_into_py(py, async move {
            let client = plugins::registry_client(Vec::new(), false);
            client.list_tags(&repository).await.map_err(plugin_error)
        })
    }

    /// Resolves a reference to the newest build compatible with this host.
    ///
    /// Does not download anything.
    fn resolve_plugin<'py>(
        &self,
        py: Python<'py>,
        reference: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        future_into_py(py, async move {
            let client = plugins::registry_client(Vec::new(), false);
            let resolved = plugins::resolve(&client, &reference)
                .await
                .map_err(incompatible_plugin)?;
            Python::attach(|py| resolved_to_py(py, &resolved).map(Bound::unbind))
        })
    }

    /// Downloads, verifies, installs and loads a plugin.
    ///
    /// The newest build compatible with this host is selected automatically, so
    /// callers do not need to know that plugins are published per platform.
    #[pyo3(signature = (
        reference,
        *,
        directory = None,
        verify = false,
        require_signed = false,
        trusted_identities = None,
        load = true,
    ))]
    #[allow(clippy::too_many_arguments)]
    fn install_plugin<'py>(
        &self,
        py: Python<'py>,
        reference: String,
        directory: Option<PathBuf>,
        verify: bool,
        require_signed: bool,
        trusted_identities: Option<Vec<(String, String)>>,
        load: bool,
    ) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            let client = plugins::registry_client(
                trusted_identities.unwrap_or_default(),
                verify || require_signed,
            );
            let resolved = plugins::resolve(&client, &reference)
                .await
                .map_err(incompatible_plugin)?;

            let directory = match directory {
                Some(directory) => directory,
                None => inner.default_plugin_dir().await.map_err(plugin_error)?,
            };
            tokio::fs::create_dir_all(&directory)
                .await
                .map_err(plugin_error)?;

            let file_name = plugins::plugin_file_name(&resolved.plugin_type, &resolved.kind);
            let download = client
                .download_plugin(&resolved.reference, &directory, &file_name)
                .await
                .map_err(plugin_error)?;

            let status = plugins::signature_status(&download.verification);
            if require_signed && status != "verified" {
                return Err(error(
                    DrasiErrorCode::PluginSignatureInvalid,
                    format!(
                        "'{}' could not be verified (signature status: {status});                          pass require_signed=False to install it anyway",
                        resolved.reference
                    ),
                ));
            }

            inner
                .plugins
                .record_install(&resolved, &download.path)
                .await;

            if load {
                inner
                    .plugins
                    .load_file(&inner.core, &inner.id, &download.path)
                    .await
                    .map_err(incompatible_plugin)?;
            }

            Python::attach(|py| {
                let result = resolved_to_py(py, &resolved)?;
                result.set_item("path", download.path.to_string_lossy().as_ref())?;
                result.set_item("verification", status)?;
                result.set_item("loaded", load)?;
                Ok(result.unbind())
            })
        })
    }

    /// Downloads an exact plugin reference, without resolving a compatible one.
    ///
    /// Use `install_plugin` unless you specifically want to pin an artifact;
    /// this does no compatibility checking before downloading, so a reference
    /// for another platform will download and then fail to load.
    #[pyo3(signature = (reference, directory, filename, *, verify = false, require_signed = false, trusted_identities = None))]
    #[allow(clippy::too_many_arguments)]
    fn pull_plugin<'py>(
        &self,
        py: Python<'py>,
        reference: String,
        directory: PathBuf,
        filename: String,
        verify: bool,
        require_signed: bool,
        trusted_identities: Option<Vec<(String, String)>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        future_into_py(py, async move {
            let client = plugins::registry_client(
                trusted_identities.unwrap_or_default(),
                verify || require_signed,
            );
            tokio::fs::create_dir_all(&directory)
                .await
                .map_err(plugin_error)?;
            let download = client
                .download_plugin(&reference, &directory, &filename)
                .await
                .map_err(plugin_error)?;

            let status = plugins::signature_status(&download.verification);
            if require_signed && status != "verified" {
                return Err(error(
                    DrasiErrorCode::PluginSignatureInvalid,
                    format!("'{reference}' could not be verified (signature status: {status})"),
                ));
            }

            Python::attach(|py| {
                let result = PyDict::new(py);
                result.set_item("reference", &reference)?;
                result.set_item("path", download.path.to_string_lossy().as_ref())?;
                result.set_item("verification", status)?;
                Ok(result.unbind())
            })
        })
    }

    /// Writes a `plugins.lock` pinning every plugin installed in this session.
    fn write_lockfile<'py>(
        &self,
        py: Python<'py>,
        directory: PathBuf,
    ) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            inner
                .plugins
                .write_lockfile(&directory)
                .await
                .map_err(plugin_error)
        })
    }

    /// Reads a `plugins.lock` and returns what it pins.
    #[staticmethod]
    fn read_lockfile(py: Python<'_>, directory: PathBuf) -> PyResult<Bound<'_, PyAny>> {
        let entries = PluginHost::read_lockfile(&directory).map_err(plugin_error)?;
        let list = PyList::empty(py);
        for entry in entries {
            let item = PyDict::new(py);
            item.set_item("reference", &entry.reference)?;
            item.set_item("version", &entry.version)?;
            item.set_item("digest", &entry.digest)?;
            item.set_item("filename", &entry.filename)?;
            item.set_item("platform", &entry.platform)?;
            item.set_item("file_hash", entry.file_hash.clone())?;
            item.set_item("sdk_version", &entry.sdk_version)?;
            item.set_item("core_version", &entry.core_version)?;
            item.set_item("lib_version", &entry.lib_version)?;
            list.append(item)?;
        }
        Ok(list.into_any())
    }

    /// Installs exactly what a `plugins.lock` pins.
    ///
    /// Each entry names a digest, so this reinstalls the same artifacts rather
    /// than resolving newer ones.
    #[pyo3(signature = (directory, *, load = true))]
    fn install_from_lockfile<'py>(
        &self,
        py: Python<'py>,
        directory: PathBuf,
        load: bool,
    ) -> PyResult<Bound<'py, PyAny>> {
        let entries = PluginHost::read_lockfile(&directory).map_err(plugin_error)?;
        let inner = self.inner();
        future_into_py(py, async move {
            let client = plugins::registry_client(Vec::new(), false);
            let mut installed = Vec::new();
            for entry in entries {
                let download = client
                    .download_plugin(&entry.reference, &directory, &entry.filename)
                    .await
                    .map_err(plugin_error)?;

                if let Some(expected) = &entry.file_hash {
                    let actual = plugins::file_hash(&download.path).map_err(plugin_error)?;
                    if !actual.eq_ignore_ascii_case(expected) {
                        return Err(error(
                            DrasiErrorCode::PluginSignatureInvalid,
                            format!(
                                "'{}' does not match the hash recorded in plugins.lock",
                                entry.reference
                            ),
                        ));
                    }
                }

                if load {
                    inner
                        .plugins
                        .load_file(&inner.core, &inner.id, &download.path)
                        .await
                        .map_err(incompatible_plugin)?;
                }
                installed.push(entry.reference);
            }
            Ok(installed)
        })
    }

    /// The OpenAPI schema describing a source plugin's configuration.
    fn source_config_schema<'py>(
        &self,
        py: Python<'py>,
        kind: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            let descriptor = inner
                .plugins
                .source_descriptor(&kind)
                .await
                .ok_or_else(|| {
                    error(
                        DrasiErrorCode::UnknownSourceKind,
                        format!("no source plugin registered for kind '{kind}'"),
                    )
                })?;
            let name = descriptor.config_schema_name().to_string();
            let schema = descriptor.config_schema_json();
            Python::attach(|py| schema_to_py(py, &name, &schema).map(Bound::unbind))
        })
    }

    /// The OpenAPI schema describing a reaction plugin's configuration.
    fn reaction_config_schema<'py>(
        &self,
        py: Python<'py>,
        kind: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            let descriptor = inner
                .plugins
                .reaction_descriptor(&kind)
                .await
                .ok_or_else(|| {
                    error(
                        DrasiErrorCode::UnknownReactionKind,
                        format!("no reaction plugin registered for kind '{kind}'"),
                    )
                })?;
            let name = descriptor.config_schema_name().to_string();
            let schema = descriptor.config_schema_json();
            Python::attach(|py| schema_to_py(py, &name, &schema).map(Bound::unbind))
        })
    }

    /// The OpenAPI schema describing a bootstrap plugin's configuration.
    fn bootstrap_config_schema<'py>(
        &self,
        py: Python<'py>,
        kind: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            let descriptor = inner
                .plugins
                .bootstrap_descriptor(&kind)
                .await
                .ok_or_else(|| {
                    error(
                        DrasiErrorCode::UnknownBootstrapKind,
                        format!("no bootstrap plugin registered for kind '{kind}'"),
                    )
                })?;
            let name = descriptor.config_schema_name().to_string();
            let schema = descriptor.config_schema_json();
            Python::attach(|py| schema_to_py(py, &name, &schema).map(Bound::unbind))
        })
    }

    // ------------------------------------------------ plugin-backed components

    /// Adds a source provided by a loaded plugin.
    #[pyo3(signature = (kind, id, config = None, *, auto_start = true))]
    fn add_source<'py>(
        &self,
        py: Python<'py>,
        kind: String,
        id: String,
        config: Option<&Bound<'py, PyAny>>,
        auto_start: bool,
    ) -> PyResult<Bound<'py, PyAny>> {
        let config = match config {
            Some(value) => py_to_json(value)?,
            None => serde_json::json!({}),
        };
        let inner = self.inner();
        future_into_py(py, async move {
            let descriptor = inner
                .plugins
                .source_descriptor(&kind)
                .await
                .ok_or_else(|| unknown_kind(DrasiErrorCode::UnknownSourceKind, "source", &kind))?;
            let source = descriptor
                .create_source(&id, &config, auto_start)
                .await
                .map_err(engine_error)?;
            inner
                .core
                .add_source_with_metadata(
                    BoxedSource(source),
                    HashMap::from([("pluginKind".to_string(), kind)]),
                )
                .await
                .map_err(engine_error)
        })
    }

    /// Adds a reaction provided by a loaded plugin.
    #[pyo3(signature = (kind, id, query_ids, config = None, *, auto_start = true))]
    fn add_reaction<'py>(
        &self,
        py: Python<'py>,
        kind: String,
        id: String,
        query_ids: Vec<String>,
        config: Option<&Bound<'py, PyAny>>,
        auto_start: bool,
    ) -> PyResult<Bound<'py, PyAny>> {
        let config = match config {
            Some(value) => py_to_json(value)?,
            None => serde_json::json!({}),
        };
        let inner = self.inner();
        future_into_py(py, async move {
            let descriptor = inner
                .plugins
                .reaction_descriptor(&kind)
                .await
                .ok_or_else(|| {
                    unknown_kind(DrasiErrorCode::UnknownReactionKind, "reaction", &kind)
                })?;
            let reaction = descriptor
                .create_reaction(&id, query_ids, &config, auto_start)
                .await
                .map_err(engine_error)?;
            inner
                .core
                .add_reaction_with_metadata(
                    BoxedReaction(reaction),
                    HashMap::from([("pluginKind".to_string(), kind)]),
                )
                .await
                .map_err(engine_error)
        })
    }

    /// Replaces a source's configuration in place.
    ///
    /// The engine takes a component rather than a config, so this rebuilds one
    /// from the plugin descriptor. The id cannot change.
    #[pyo3(signature = (kind, id, config = None, *, auto_start = true))]
    fn update_source<'py>(
        &self,
        py: Python<'py>,
        kind: String,
        id: String,
        config: Option<&Bound<'py, PyAny>>,
        auto_start: bool,
    ) -> PyResult<Bound<'py, PyAny>> {
        let config = match config {
            Some(value) => py_to_json(value)?,
            None => serde_json::json!({}),
        };
        let inner = self.inner();
        future_into_py(py, async move {
            let descriptor = inner
                .plugins
                .source_descriptor(&kind)
                .await
                .ok_or_else(|| unknown_kind(DrasiErrorCode::UnknownSourceKind, "source", &kind))?;
            let source = descriptor
                .create_source(&id, &config, auto_start)
                .await
                .map_err(engine_error)?;
            inner
                .core
                .update_source(&id, BoxedSource(source))
                .await
                .map_err(engine_error)
        })
    }

    #[pyo3(signature = (id, *, cleanup = false))]
    fn remove_source<'py>(
        &self,
        py: Python<'py>,
        id: String,
        cleanup: bool,
    ) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            inner
                .core
                .remove_source(&id, cleanup)
                .await
                .map_err(engine_error)?;
            inner.python_sources.lock().await.remove(&id);
            Ok(())
        })
    }

    fn start_source<'py>(&self, py: Python<'py>, id: String) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            inner.core.start_source(&id).await.map_err(engine_error)
        })
    }

    fn stop_source<'py>(&self, py: Python<'py>, id: String) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            inner.core.stop_source(&id).await.map_err(engine_error)
        })
    }

    /// The current status of a source, such as `"Running"`.
    fn get_source_status<'py>(&self, py: Python<'py>, id: String) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            inner
                .core
                .get_source_status(&id)
                .await
                .map(|status| format!("{status:?}"))
                .map_err(engine_error)
        })
    }

    fn list_sources<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            let sources = inner.core.list_sources().await.map_err(engine_error)?;
            Ok(status_pairs(sources))
        })
    }

    /// Replaces a reaction's configuration in place.
    #[pyo3(signature = (kind, id, query_ids, config = None, *, auto_start = true))]
    fn update_reaction<'py>(
        &self,
        py: Python<'py>,
        kind: String,
        id: String,
        query_ids: Vec<String>,
        config: Option<&Bound<'py, PyAny>>,
        auto_start: bool,
    ) -> PyResult<Bound<'py, PyAny>> {
        let config = match config {
            Some(value) => py_to_json(value)?,
            None => serde_json::json!({}),
        };
        let inner = self.inner();
        future_into_py(py, async move {
            let descriptor = inner
                .plugins
                .reaction_descriptor(&kind)
                .await
                .ok_or_else(|| {
                    unknown_kind(DrasiErrorCode::UnknownReactionKind, "reaction", &kind)
                })?;
            let reaction = descriptor
                .create_reaction(&id, query_ids, &config, auto_start)
                .await
                .map_err(engine_error)?;
            inner
                .core
                .update_reaction(&id, BoxedReaction(reaction))
                .await
                .map_err(engine_error)
        })
    }

    #[pyo3(signature = (id, *, cleanup = false))]
    fn remove_reaction<'py>(
        &self,
        py: Python<'py>,
        id: String,
        cleanup: bool,
    ) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            inner
                .core
                .remove_reaction(&id, cleanup)
                .await
                .map_err(engine_error)
        })
    }

    fn start_reaction<'py>(&self, py: Python<'py>, id: String) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            inner.core.start_reaction(&id).await.map_err(engine_error)
        })
    }

    fn stop_reaction<'py>(&self, py: Python<'py>, id: String) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            inner.core.stop_reaction(&id).await.map_err(engine_error)
        })
    }

    /// The current status of a reaction, such as `"Running"`.
    fn get_reaction_status<'py>(&self, py: Python<'py>, id: String) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            inner
                .core
                .get_reaction_status(&id)
                .await
                .map(|status| format!("{status:?}"))
                .map_err(engine_error)
        })
    }

    fn list_reactions<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            let reactions = inner.core.list_reactions().await.map_err(engine_error)?;
            Ok(status_pairs(reactions))
        })
    }

    // ------------------------------------------------- Python-defined sources

    /// Registers a source that you push changes into with `push_change`.
    #[pyo3(signature = (id, *, auto_start = true))]
    fn add_python_source<'py>(
        &self,
        py: Python<'py>,
        id: String,
        auto_start: bool,
    ) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            let source = Arc::new(PythonSource::new(&id, auto_start).map_err(engine_error)?);
            inner
                .core
                .add_source(SharedSource(Arc::clone(&source)))
                .await
                .map_err(engine_error)?;
            inner.python_sources.lock().await.insert(id, source);
            Ok(())
        })
    }

    /// Emits a change from a Python-defined source.
    fn push_change<'py>(
        &self,
        py: Python<'py>,
        source_id: String,
        change: &Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        // Validate and convert eagerly: a malformed change should raise before
        // the caller ever awaits, and the conversion needs the GIL anyway.
        let change = source_change_from_py(&source_id, change)?;
        let inner = self.inner();
        future_into_py(py, async move {
            let source = inner
                .python_sources
                .lock()
                .await
                .get(&source_id)
                .cloned()
                .ok_or_else(|| {
                    error(
                        DrasiErrorCode::NoPySource,
                        format!("'{source_id}' is not a Python-defined source"),
                    )
                })?;
            source.push(change).await.map_err(engine_error)
        })
    }

    /// Registers a reaction that calls `callback` with each query result.
    fn add_python_reaction<'py>(
        &self,
        py: Python<'py>,
        id: String,
        query_ids: Vec<String>,
        callback: Py<PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        if !callback.bind(py).is_callable() {
            return Err(error(
                DrasiErrorCode::ConfigInvalid,
                "a reaction callback must be callable",
            ));
        }
        let inner = self.inner();
        future_into_py(py, async move {
            inner
                .core
                .add_reaction(PythonReaction::new(&id, query_ids, callback))
                .await
                .map_err(engine_error)
        })
    }
}

/// Tuning knobs accepted alongside a query definition.
#[derive(Default)]
pub struct QueryTuning {
    pub auto_start: Option<bool>,
    pub enable_bootstrap: Option<bool>,
    pub bootstrap_timeout_seconds: Option<u64>,
    pub priority_queue_capacity: Option<usize>,
    pub dispatch_buffer_capacity: Option<usize>,
    pub outbox_capacity: Option<usize>,
    pub dispatch_mode: Option<String>,
}

/// Builds a query configuration, validating the language up front.
fn build_query(
    id: &str,
    query: &str,
    sources: &[String],
    language: &str,
    joins: Option<&Bound<'_, PyAny>>,
    tuning: QueryTuning,
) -> PyResult<drasi_lib::config::QueryConfig> {
    let mut builder = match language.trim().to_ascii_lowercase().as_str() {
        "cypher" => Query::cypher(id),
        "gql" => Query::gql(id),
        other => {
            return Err(error(
                DrasiErrorCode::UnknownQueryLanguage,
                format!("unknown query language '{other}', expected 'cypher' or 'gql'"),
            ))
        }
    };

    builder = builder.query(query);
    for source in sources {
        builder = builder.from_source(source);
    }
    if let Some(joins) = joins {
        builder = builder.with_joins(parse_joins(joins)?);
    }
    if let Some(auto_start) = tuning.auto_start {
        builder = builder.auto_start(auto_start);
    }
    if let Some(enable) = tuning.enable_bootstrap {
        builder = builder.enable_bootstrap(enable);
    }
    if let Some(seconds) = tuning.bootstrap_timeout_seconds {
        builder = builder.with_bootstrap_timeout_secs(seconds);
    }
    if let Some(capacity) = tuning.priority_queue_capacity {
        builder = builder.with_priority_queue_capacity(capacity);
    }
    if let Some(capacity) = tuning.dispatch_buffer_capacity {
        builder = builder.with_dispatch_buffer_capacity(capacity);
    }
    if let Some(capacity) = tuning.outbox_capacity {
        builder = builder.with_outbox_capacity(capacity);
    }
    if let Some(mode) = tuning.dispatch_mode {
        builder = builder.with_dispatch_mode(parse_dispatch_mode(&mode)?);
    }
    Ok(builder.build())
}

fn parse_dispatch_mode(mode: &str) -> PyResult<drasi_lib::DispatchMode> {
    match mode.trim().to_ascii_lowercase().as_str() {
        "channel" => Ok(drasi_lib::DispatchMode::Channel),
        "broadcast" => Ok(drasi_lib::DispatchMode::Broadcast),
        other => Err(error(
            DrasiErrorCode::ConfigInvalid,
            format!("unknown dispatch mode '{other}', expected 'channel' or 'broadcast'"),
        )),
    }
}

/// Parses `[{"id": ..., "keys": [{"label": ..., "property": ...}]}]`.
fn parse_joins(joins: &Bound<'_, PyAny>) -> PyResult<Vec<QueryJoinConfig>> {
    let invalid = |detail: &str| {
        error(
            DrasiErrorCode::ConfigInvalid,
            format!("invalid join definition: {detail}"),
        )
    };

    let mut parsed = Vec::new();
    for join in joins.try_iter()? {
        let join = join?;
        let join = join
            .cast::<PyDict>()
            .map_err(|_| invalid("each join must be a mapping"))?;
        let id: String = join
            .get_item("id")?
            .ok_or_else(|| invalid("a join requires an 'id'"))?
            .extract()
            .map_err(|_| invalid("'id' must be a string"))?;

        let mut keys = Vec::new();
        let raw_keys = join
            .get_item("keys")?
            .ok_or_else(|| invalid("a join requires 'keys'"))?;
        for key in raw_keys.try_iter()? {
            let key = key?;
            let key = key
                .cast::<PyDict>()
                .map_err(|_| invalid("each join key must be a mapping"))?;
            keys.push(QueryJoinKeyConfig {
                label: key
                    .get_item("label")?
                    .ok_or_else(|| invalid("a join key requires a 'label'"))?
                    .extract()
                    .map_err(|_| invalid("'label' must be a string"))?,
                property: key
                    .get_item("property")?
                    .ok_or_else(|| invalid("a join key requires a 'property'"))?
                    .extract()
                    .map_err(|_| invalid("'property' must be a string"))?,
            });
        }

        if keys.is_empty() {
            return Err(invalid("a join requires at least one key"));
        }
        parsed.push(QueryJoinConfig { id, keys });
    }
    Ok(parsed)
}

/// Converts `(id, status)` pairs into the shape returned to Python.
fn status_pairs(entries: Vec<(String, ComponentStatus)>) -> Vec<(String, String)> {
    entries
        .into_iter()
        .map(|(id, status)| (id, format!("{status:?}")))
        .collect()
}

fn summary_to_py(py: Python<'_>, summary: LoadSummary) -> PyResult<Bound<'_, PyDict>> {
    let result = PyDict::new(py);
    result.set_item("plugins", summary.plugins)?;
    result.set_item("sources", summary.sources)?;
    result.set_item("reactions", summary.reactions)?;
    result.set_item("bootstrap", summary.bootstrap)?;
    Ok(result)
}

fn resolved_to_py<'py>(py: Python<'py>, resolved: &Resolved) -> PyResult<Bound<'py, PyDict>> {
    let result = PyDict::new(py);
    result.set_item("reference", &resolved.reference)?;
    result.set_item("kind", &resolved.kind)?;
    result.set_item("plugin_type", &resolved.plugin_type)?;
    result.set_item("version", &resolved.version)?;
    result.set_item("target_triple", &resolved.target_triple)?;
    result.set_item("sdk_version", &resolved.sdk_version)?;
    result.set_item("core_version", &resolved.core_version)?;
    result.set_item("lib_version", &resolved.lib_version)?;
    Ok(result)
}

fn schema_to_py<'py>(py: Python<'py>, name: &str, schema: &str) -> PyResult<Bound<'py, PyDict>> {
    let parsed: serde_json::Value = serde_json::from_str(schema).map_err(|err| {
        error(
            DrasiErrorCode::ConfigInvalid,
            format!("plugin returned an unparsable config schema: {err}"),
        )
    })?;
    let result = PyDict::new(py);
    result.set_item("name", name)?;
    result.set_item("schema", json_to_py(py, &parsed)?)?;
    Ok(result)
}

fn unknown_kind(code: DrasiErrorCode, component: &str, kind: &str) -> PyErr {
    error(
        code,
        format!(
            "unknown {component} kind '{kind}'; load a plugin that provides it, \
             for example with install_plugin('{component}/{kind}')"
        ),
    )
}

/// A registry or loader failure.
fn plugin_error(err: impl std::fmt::Display) -> PyErr {
    error(DrasiErrorCode::PluginNotFound, err.to_string())
}

/// A plugin that cannot be used by this host.
///
/// Reports what the host offers, since the usual cause is an architecture or
/// version mismatch that is otherwise invisible from Python.
fn incompatible_plugin(err: impl std::fmt::Display) -> PyErr {
    error(
        DrasiErrorCode::PluginIncompatible,
        format!("{err}\nthis host is {}", plugins::describe_host()),
    )
}

/// Builds a stream fed from a broadcast subscription, replaying history first.
fn broadcast_stream<T>(
    description: String,
    history: Vec<T>,
    receiver: tokio::sync::broadcast::Receiver<T>,
) -> Stream
where
    T: serde::Serialize + Clone + Send + Sync + 'static,
{
    let (rx, sender) = streams::channel();
    streams::pump_broadcast(history, receiver, sender);
    Stream::new(rx, description)
}

/// Rejects a non-callable before any work is scheduled.
fn require_callable(py: Python<'_>, callback: &Py<PyAny>) -> PyResult<()> {
    if callback.bind(py).is_callable() {
        Ok(())
    } else {
        Err(error(
            DrasiErrorCode::ConfigInvalid,
            "a stream callback must be callable",
        ))
    }
}
