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

//! Shared tokio runtime for the Drasi Python bindings.
//!
//! Every async binding method hands its future to this runtime via
//! [`pyo3_async_runtimes::tokio::future_into_py`], which drives it off-GIL and
//! resolves the corresponding Python awaitable on the caller's asyncio loop.

use std::sync::OnceLock;

use tokio::runtime::{Builder, Runtime};

static RUNTIME: OnceLock<Runtime> = OnceLock::new();

/// Returns the process-wide multi-threaded tokio runtime, building it on first use.
pub fn runtime() -> &'static Runtime {
    RUNTIME.get_or_init(|| {
        Builder::new_multi_thread()
            .enable_all()
            .thread_name("drasi-worker")
            .build()
            .expect("failed to build the Drasi tokio runtime")
    })
}

/// Points `pyo3-async-runtimes` at our runtime so `future_into_py` uses it.
pub fn install() {
    pyo3_async_runtimes::tokio::init_with_runtime(runtime())
        .expect("failed to install the Drasi tokio runtime");
}
