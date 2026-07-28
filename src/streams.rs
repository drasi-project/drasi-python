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

//! Observing an engine as it runs.
//!
//! Three things can be streamed, and they are not the same:
//!
//! * **Events** — lifecycle transitions of a component (Starting, Running,
//!   Error, Stopped).
//! * **Logs** — log lines emitted by a component, including from plugins.
//! * **Results** — the actual diffs a continuous query produces. These reach
//!   subscribers through a reaction, so a result stream registers one.
//!
//! Each is exposed as an async iterator, and as a callback for parity with the
//! Node.js binding.

use std::sync::Arc;

use pyo3::exceptions::PyStopAsyncIteration;
use pyo3::prelude::*;
use pyo3_async_runtimes::tokio::future_into_py;
use serde::Serialize;
use serde_json::Value;
use tokio::sync::{mpsc, Mutex};

use crate::conversions::json_to_py;
use crate::errors::{error, DrasiErrorCode};

/// How many items a stream buffers before the producer applies backpressure.
const BUFFER: usize = 256;

/// One item from a stream: a payload, or a gap where items were dropped.
pub enum StreamItem {
    Value(Value),
    /// The consumer fell far enough behind that the engine discarded items.
    Lagged(u64),
}

/// A cloneable sender for pumping items into a [`Stream`].
pub type StreamSender = mpsc::Sender<StreamItem>;

/// An async iterator over engine activity.
///
/// Iteration ends when the engine stops producing — closing the engine
/// terminates any open stream rather than leaving it hanging.
#[pyclass(module = "drasi._drasi", name = "Stream")]
pub struct Stream {
    receiver: Arc<Mutex<mpsc::Receiver<StreamItem>>>,
    description: String,
}

/// Creates the channel a stream is fed through.
///
/// The receiver is handed either to [`Stream`] for `async for`, or to
/// [`pump_callback`] for the callback form, so both share one producer.
pub fn channel() -> (mpsc::Receiver<StreamItem>, StreamSender) {
    let (sender, receiver) = mpsc::channel(BUFFER);
    (receiver, sender)
}

impl Stream {
    pub fn new(receiver: mpsc::Receiver<StreamItem>, description: impl Into<String>) -> Self {
        Self {
            receiver: Arc::new(Mutex::new(receiver)),
            description: description.into(),
        }
    }
}

#[pymethods]
impl Stream {
    fn __aiter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __anext__<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let receiver = Arc::clone(&self.receiver);
        let description = self.description.clone();
        future_into_py(py, async move {
            let item = receiver.lock().await.recv().await;
            match item {
                Some(StreamItem::Value(value)) => {
                    Python::attach(|py| json_to_py(py, &value).map(|value| value.unbind()))
                }
                // Reported rather than skipped: silently losing events would
                // make a slow consumer look like an idle engine.
                Some(StreamItem::Lagged(count)) => Err(error(
                    DrasiErrorCode::StreamLagged,
                    format!(
                        "{description} dropped {count} item(s) because they were not \
                         consumed quickly enough; iterate faster or buffer them yourself"
                    ),
                )),
                None => Err(PyStopAsyncIteration::new_err(())),
            }
        })
    }

    fn __repr__(&self) -> String {
        format!("Stream({})", self.description)
    }
}

/// Serialises a payload and forwards it, returning false once the receiver is gone.
async fn forward<T: Serialize>(sender: &StreamSender, payload: &T) -> bool {
    match serde_json::to_value(payload) {
        Ok(value) => sender.send(StreamItem::Value(value)).await.is_ok(),
        Err(err) => {
            log::error!("could not serialise a stream item: {err}");
            true
        }
    }
}

/// Pumps a broadcast subscription into a stream, replaying history first.
///
/// Spawned as a task; it ends when the engine closes the broadcast or the
/// consumer drops the stream.
pub fn pump_broadcast<T>(
    history: Vec<T>,
    mut receiver: tokio::sync::broadcast::Receiver<T>,
    sender: StreamSender,
) where
    T: Serialize + Clone + Send + Sync + 'static,
{
    tokio::spawn(async move {
        for item in history {
            if !forward(&sender, &item).await {
                return;
            }
        }
        loop {
            match receiver.recv().await {
                Ok(item) => {
                    if !forward(&sender, &item).await {
                        return;
                    }
                }
                Err(tokio::sync::broadcast::error::RecvError::Lagged(count)) => {
                    if sender.send(StreamItem::Lagged(count)).await.is_err() {
                        return;
                    }
                }
                Err(tokio::sync::broadcast::error::RecvError::Closed) => return,
            }
        }
    });
}

/// Pumps a `futures::Stream` into a stream.
pub fn pump_stream<S, T>(stream: S, sender: StreamSender)
where
    S: futures_util::Stream<Item = T> + Send + 'static,
    T: Serialize + Send + Sync + 'static,
{
    tokio::spawn(async move {
        use futures_util::StreamExt;
        let mut stream = Box::pin(stream);
        while let Some(item) = stream.next().await {
            if !forward(&sender, &item).await {
                return;
            }
        }
    });
}

/// Invokes a Python callable for each item, for parity with the Node.js binding.
///
/// Runs on a tokio task, so the GIL is acquired per item. A callback that
/// raises is logged and iteration continues, matching the fire-and-forget
/// semantics of the Node.js callbacks.
pub fn pump_callback(mut receiver: mpsc::Receiver<StreamItem>, callback: Py<PyAny>, label: String) {
    tokio::spawn(async move {
        while let Some(item) = receiver.recv().await {
            let outcome = Python::attach(|py| -> PyResult<()> {
                match item {
                    StreamItem::Value(ref value) => {
                        let payload = json_to_py(py, value)?;
                        callback.call1(py, (payload,))?;
                    }
                    StreamItem::Lagged(count) => {
                        log::warn!("{label} dropped {count} item(s); the callback is too slow");
                    }
                }
                Ok(())
            });
            if let Err(err) = outcome {
                log::error!("{label} callback raised: {err}");
            }
        }
    });
}
