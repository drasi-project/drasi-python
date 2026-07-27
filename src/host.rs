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

//! Host version introspection.
//!
//! A Drasi plugin is a platform-specific cdylib that is only loadable by a host
//! built against a compatible set of Drasi crates. Exposing this information to
//! Python makes "why was my plugin rejected?" answerable without guesswork.

use pyo3::prelude::*;
use pyo3::types::{PyDict, PyDictMethods};

use crate::{DRASI_CORE_VERSION, DRASI_LIB_VERSION, DRASI_SDK_VERSION};

/// The FFI ABI version this host implements.
///
/// Deliberately decoupled from the `drasi-plugin-sdk` crate version: it
/// identifies the layout of the `#[repr(C)]` envelope structs and the wire
/// format used across the plugin boundary.
pub fn ffi_sdk_version() -> &'static str {
    drasi_plugin_sdk::ffi::metadata::FFI_SDK_VERSION
}

/// The Rust target triple this host was compiled for.
///
/// A plugin must report exactly this triple or it will be rejected at load time.
pub fn target_triple() -> &'static str {
    drasi_plugin_sdk::ffi::metadata::TARGET_TRIPLE
}

/// Returns the version and platform information used to decide plugin compatibility.
#[pyfunction]
pub fn host_info(py: Python<'_>) -> PyResult<Bound<'_, PyDict>> {
    let info = PyDict::new(py);
    info.set_item("target_triple", target_triple())?;
    info.set_item("ffi_sdk_version", ffi_sdk_version())?;
    info.set_item("sdk_version", DRASI_SDK_VERSION)?;
    info.set_item("core_version", DRASI_CORE_VERSION)?;
    info.set_item("lib_version", DRASI_LIB_VERSION)?;
    Ok(info)
}
