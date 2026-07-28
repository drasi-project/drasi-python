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
use std::sync::Arc;
use std::time::Duration;

use drasi_lib::api::Query;
use drasi_lib::config::{QueryJoinConfig, QueryJoinKeyConfig};
use drasi_lib::{ComponentStatus, DrasiLib};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyString};
use pyo3_async_runtimes::tokio::future_into_py;
use tokio::sync::Mutex;

use crate::components::{BoxedReaction, BoxedSource, PythonReaction, PythonSource, SharedSource};
use crate::conversions::{json_to_py, py_to_json, source_change_from_py};
use crate::errors::{engine_error, error, DrasiErrorCode};
use crate::plugins::{self, LoadSummary, PluginHost, Resolved};
use crate::stores::CreateOptions;

/// Shared engine state.
///
/// Held behind an `Arc` so every async method can clone a handle into a
/// `Send + 'static` future without borrowing `self` across an await point.
pub struct Inner {
    pub id: String,
    pub core: DrasiLib,
    /// Python-defined sources, kept so `push_change` can reach them directly.
    pub python_sources: Mutex<HashMap<String, Arc<PythonSource>>>,
    pub plugins: PluginHost,
    /// Directory `install_plugin` writes to when the caller does not pick one.
    default_plugin_dir: Mutex<Option<PathBuf>>,
}

impl Inner {
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
                    plugins: PluginHost::new(secrets),
                    default_plugin_dir: Mutex::new(None),
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
    #[pyo3(signature = (id, query, sources, *, language = "cypher", joins = None))]
    fn add_query<'py>(
        &self,
        py: Python<'py>,
        id: String,
        query: String,
        sources: Vec<String>,
        language: &str,
        joins: Option<&Bound<'py, PyAny>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let config = build_query(&id, &query, &sources, language, joins)?;
        let inner = self.inner();
        future_into_py(py, async move {
            inner.core.add_query(config).await.map_err(engine_error)
        })
    }

    /// Replaces the definition of an existing query.
    #[pyo3(signature = (id, query, sources, *, language = "cypher", joins = None))]
    fn update_query<'py>(
        &self,
        py: Python<'py>,
        id: String,
        query: String,
        sources: Vec<String>,
        language: &str,
        joins: Option<&Bound<'py, PyAny>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let config = build_query(&id, &query, &sources, language, joins)?;
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

    fn list_sources<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner();
        future_into_py(py, async move {
            let sources = inner.core.list_sources().await.map_err(engine_error)?;
            Ok(status_pairs(sources))
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

/// Builds a query configuration, validating the language up front.
fn build_query(
    id: &str,
    query: &str,
    sources: &[String],
    language: &str,
    joins: Option<&Bound<'_, PyAny>>,
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
    Ok(builder.build())
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
