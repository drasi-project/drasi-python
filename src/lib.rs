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

//! Native extension module backing the `drasi` Python package.
//!
//! This crate must never install a custom global allocator. The host and any
//! loaded cdylib plugin exchange ownership of heap allocations across the FFI
//! boundary (`Box::into_raw` / `Box::from_raw`), which is only sound while both
//! sides use the process-global system allocator.

mod components;
mod conversions;
mod engine;
mod errors;
mod host;
mod plugins;
mod runtime;
mod secrets;
mod stores;
mod streams;

use pyo3::prelude::*;

/// Versions of the Drasi crates this binding was built against.
///
/// Published plugins are annotated with the versions they were built against,
/// and the host only accepts a plugin whose versions match these on
/// `major.minor`.
pub const DRASI_CORE_VERSION: &str = "0.5.7";
pub const DRASI_LIB_VERSION: &str = "0.8.9";
pub const DRASI_SDK_VERSION: &str = "0.10.0";

#[pymodule]
fn _drasi(module: &Bound<'_, PyModule>) -> PyResult<()> {
    runtime::install();

    module.add("__version__", env!("CARGO_PKG_VERSION"))?;
    module.add("DRASI_CORE_VERSION", DRASI_CORE_VERSION)?;
    module.add("DRASI_LIB_VERSION", DRASI_LIB_VERSION)?;
    module.add("DRASI_SDK_VERSION", DRASI_SDK_VERSION)?;

    module.add_function(wrap_pyfunction!(host::host_info, module)?)?;
    module.add_class::<engine::Drasi>()?;
    module.add_class::<streams::Stream>()?;
    errors::register(module)?;

    Ok(())
}
