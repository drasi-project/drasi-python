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
use std::sync::Arc;

use drasi_lib::api::Query;
use drasi_lib::config::{QueryJoinConfig, QueryJoinKeyConfig};
use drasi_lib::DrasiLib;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyString};
use pyo3_async_runtimes::tokio::future_into_py;
use tokio::sync::Mutex;

use crate::components::{PythonReaction, PythonSource, SharedSource};
use crate::conversions::{json_to_py, source_change_from_py};
use crate::errors::{engine_error, error, DrasiErrorCode};

/// Shared engine state.
///
/// Held behind an `Arc` so every async method can clone a handle into a
/// `Send + 'static` future without borrowing `self` across an await point.
pub struct Inner {
    pub id: String,
    pub core: DrasiLib,
    /// Python-defined sources, kept so `push_change` can reach them directly.
    pub python_sources: Mutex<HashMap<String, Arc<PythonSource>>>,
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
    #[staticmethod]
    fn create(py: Python<'_>, id: String) -> PyResult<Bound<'_, PyAny>> {
        future_into_py(py, async move {
            let core = DrasiLib::builder()
                .with_id(id.clone())
                .build()
                .await
                .map_err(engine_error)?;
            Ok(Drasi {
                inner: Arc::new(Inner {
                    id,
                    core,
                    python_sources: Mutex::new(HashMap::new()),
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
