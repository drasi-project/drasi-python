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

use std::sync::Arc;

use drasi_lib::DrasiLib;
use pyo3::prelude::*;
use pyo3::types::PyString;
use pyo3_async_runtimes::tokio::future_into_py;

use crate::errors::engine_error;

/// Shared engine state.
///
/// Held behind an `Arc` so every async method can clone a handle into a
/// `Send + 'static` future without borrowing `self` across an await point.
pub struct Inner {
    pub id: String,
    pub core: DrasiLib,
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
                inner: Arc::new(Inner { id, core }),
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
}
