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

//! Components defined in Python rather than loaded from a plugin.
//!
//! A [`PythonSource`] is a source you push changes into from your own code, and
//! a [`PythonReaction`] delivers query results to a Python callable. Neither
//! requires Rust or a cdylib plugin.

use std::any::Any;
use std::collections::HashMap;
use std::sync::Arc;

use anyhow::Result;
use async_trait::async_trait;
use drasi_core::models::SourceChange;
use drasi_lib::channels::{QueryResult, SubscriptionResponse};
use drasi_lib::config::SourceSubscriptionSettings;
use drasi_lib::context::{ReactionRuntimeContext, SourceRuntimeContext};
use drasi_lib::{
    BootstrapProvider, ComponentStatus, Reaction, ReactionBase, ReactionBaseParams,
    ReactionRecoveryPolicy, Source, SourceBase, SourceBaseParams,
};
use pyo3::prelude::*;
use pyo3_async_runtimes::TaskLocals;
use serde_json::Value;
use tokio::sync::Mutex as TokioMutex;

use crate::conversions::json_to_py;
use crate::streams::{StreamItem, StreamSender};

/// The `type_name` reported by components defined in Python.
const PYTHON_COMPONENT_TYPE: &str = "python";

/// A source that emits the changes pushed into it from Python.
pub struct PythonSource {
    base: SourceBase,
    /// Serialises dispatch so concurrent pushes cannot be reordered.
    ///
    /// `dispatch_source_change` assigns a monotonic sequence with `fetch_add`
    /// and only then awaits its way to the subscribers, so two overlapping
    /// pushes can be delivered in the opposite order to the sequences they
    /// took. The query side treats sequence order as delivery order -
    /// `SequenceDedup::should_skip` drops anything at or below the highest
    /// sequence already seen - so the lower one is silently discarded.
    /// `asyncio.gather` over `push_change` hit this for real, losing roughly
    /// one change in twenty at a few percent of runs.
    dispatch: TokioMutex<()>,
}

impl PythonSource {
    pub fn new(id: &str, auto_start: bool) -> Result<Self> {
        let params = SourceBaseParams::new(id).with_auto_start(auto_start);
        Ok(Self {
            base: SourceBase::new(params)?,
            dispatch: TokioMutex::new(()),
        })
    }

    /// Emits a change to every subscribed query.
    pub async fn push(&self, change: SourceChange) -> Result<()> {
        let _ordered = self.dispatch.lock().await;
        self.base.dispatch_source_change(change).await
    }
}

#[async_trait]
impl Source for PythonSource {
    fn id(&self) -> &str {
        self.base.get_id()
    }

    fn type_name(&self) -> &str {
        PYTHON_COMPONENT_TYPE
    }

    fn properties(&self) -> HashMap<String, Value> {
        HashMap::new()
    }

    fn auto_start(&self) -> bool {
        self.base.get_auto_start()
    }

    async fn start(&self) -> Result<()> {
        // There is nothing to spawn: changes arrive from the application rather
        // than from a connection this source owns.
        self.base.set_status(ComponentStatus::Running, None).await;
        Ok(())
    }

    async fn stop(&self) -> Result<()> {
        self.base.stop_common().await
    }

    async fn status(&self) -> ComponentStatus {
        self.base.get_status().await
    }

    async fn subscribe(
        &self,
        settings: SourceSubscriptionSettings,
    ) -> Result<SubscriptionResponse> {
        self.base
            .subscribe_with_bootstrap(&settings, PYTHON_COMPONENT_TYPE)
            .await
    }

    fn as_any(&self) -> &dyn Any {
        self
    }

    async fn initialize(&self, context: SourceRuntimeContext) {
        self.base.initialize(context).await;
    }
}

/// A cloneable handle to a [`PythonSource`].
///
/// `DrasiLib::add_source` takes ownership of the source, but `push_change` needs
/// to reach the same instance afterwards, so the engine is handed this shared
/// wrapper and keeps the `Arc` for itself.
pub struct SharedSource(pub Arc<PythonSource>);

#[async_trait]
impl Source for SharedSource {
    fn id(&self) -> &str {
        self.0.id()
    }

    fn type_name(&self) -> &str {
        self.0.type_name()
    }

    fn properties(&self) -> HashMap<String, Value> {
        self.0.properties()
    }

    fn auto_start(&self) -> bool {
        self.0.auto_start()
    }

    async fn start(&self) -> Result<()> {
        self.0.start().await
    }

    async fn stop(&self) -> Result<()> {
        self.0.stop().await
    }

    async fn status(&self) -> ComponentStatus {
        self.0.status().await
    }

    async fn subscribe(
        &self,
        settings: SourceSubscriptionSettings,
    ) -> Result<SubscriptionResponse> {
        self.0.subscribe(settings).await
    }

    fn as_any(&self) -> &dyn Any {
        self
    }

    async fn initialize(&self, context: SourceRuntimeContext) {
        self.0.initialize(context).await;
    }
}

/// Adapts a `Box<dyn Source>` produced by a plugin descriptor.
///
/// `DrasiLib::add_source` takes `impl Source`, and `Box<dyn Source>` does not
/// itself implement the trait, so plugin-created sources are wrapped here.
pub struct BoxedSource(pub Box<dyn Source>);

#[async_trait]
impl Source for BoxedSource {
    fn id(&self) -> &str {
        self.0.id()
    }

    fn type_name(&self) -> &str {
        self.0.type_name()
    }

    fn properties(&self) -> HashMap<String, Value> {
        self.0.properties()
    }

    fn dispatch_mode(&self) -> drasi_lib::DispatchMode {
        self.0.dispatch_mode()
    }

    fn auto_start(&self) -> bool {
        self.0.auto_start()
    }

    fn supports_replay(&self) -> bool {
        self.0.supports_replay()
    }

    fn describe_schema(&self) -> Option<drasi_lib::schema::SourceSchema> {
        self.0.describe_schema()
    }

    async fn start(&self) -> Result<()> {
        self.0.start().await
    }

    async fn stop(&self) -> Result<()> {
        self.0.stop().await
    }

    async fn status(&self) -> ComponentStatus {
        self.0.status().await
    }

    async fn subscribe(
        &self,
        settings: SourceSubscriptionSettings,
    ) -> Result<SubscriptionResponse> {
        self.0.subscribe(settings).await
    }

    fn as_any(&self) -> &dyn Any {
        self
    }

    async fn deprovision(&self) -> Result<()> {
        self.0.deprovision().await
    }

    async fn initialize(&self, context: SourceRuntimeContext) {
        self.0.initialize(context).await;
    }

    async fn set_bootstrap_provider(&self, provider: Box<dyn BootstrapProvider + 'static>) {
        self.0.set_bootstrap_provider(provider).await;
    }
}

/// Adapts a `Box<dyn Reaction>` produced by a plugin descriptor.
pub struct BoxedReaction(pub Box<dyn Reaction>);

#[async_trait]
impl Reaction for BoxedReaction {
    fn id(&self) -> &str {
        self.0.id()
    }

    fn type_name(&self) -> &str {
        self.0.type_name()
    }

    fn properties(&self) -> HashMap<String, Value> {
        self.0.properties()
    }

    fn query_ids(&self) -> Vec<String> {
        self.0.query_ids()
    }

    fn auto_start(&self) -> bool {
        self.0.auto_start()
    }

    fn is_durable(&self) -> bool {
        self.0.is_durable()
    }

    fn needs_snapshot_on_fresh_start(&self) -> bool {
        self.0.needs_snapshot_on_fresh_start()
    }

    async fn initialize(&self, context: ReactionRuntimeContext) {
        self.0.initialize(context).await;
    }

    async fn start(&self) -> Result<()> {
        self.0.start().await
    }

    async fn stop(&self) -> Result<()> {
        self.0.stop().await
    }

    async fn status(&self) -> ComponentStatus {
        self.0.status().await
    }

    async fn enqueue_query_result(&self, result: QueryResult) -> Result<()> {
        self.0.enqueue_query_result(result).await
    }

    async fn deprovision(&self) -> Result<()> {
        self.0.deprovision().await
    }
}

/// A reaction that forwards query results into a [`Stream`].
///
/// Result diffs only reach subscribers through a reaction, so streaming a
/// query's results means registering one.
pub struct StreamingReaction {
    base: ReactionBase,
    /// Taken when the reaction starts, so the only remaining copy lives in the
    /// processing task. That matters for shutdown: once the task ends the last
    /// sender drops, the channel closes, and an open `async for` terminates
    /// instead of hanging.
    sender: std::sync::Mutex<Option<StreamSender>>,
}

impl StreamingReaction {
    pub fn new(id: &str, query_ids: Vec<String>, sender: StreamSender) -> Self {
        Self {
            base: ReactionBase::new(ReactionBaseParams::new(id, query_ids)),
            sender: std::sync::Mutex::new(Some(sender)),
        }
    }
}

#[async_trait]
impl Reaction for StreamingReaction {
    fn id(&self) -> &str {
        self.base.get_id()
    }

    fn type_name(&self) -> &str {
        PYTHON_COMPONENT_TYPE
    }

    fn properties(&self) -> HashMap<String, Value> {
        HashMap::new()
    }

    fn query_ids(&self) -> Vec<String> {
        self.base.get_queries().to_vec()
    }

    fn auto_start(&self) -> bool {
        self.base.get_auto_start()
    }

    async fn initialize(&self, context: ReactionRuntimeContext) {
        self.base.initialize(context).await;
    }

    async fn start(&self) -> Result<()> {
        let shutdown_rx = self.base.create_shutdown_channel().await;
        let checkpoints = self.base.read_all_checkpoints().await.unwrap_or_default();
        let base = self.base.clone_shared();
        let Some(sender) = self.sender.lock().ok().and_then(|mut held| held.take()) else {
            // Already started once; the stream it fed is gone.
            self.base.set_status(ComponentStatus::Running, None).await;
            return Ok(());
        };

        let task = tokio::spawn(async move {
            let result = base
                .run_standard_loop(shutdown_rx, checkpoints, move |event| {
                    let sender = sender.clone();
                    async move {
                        let value = serde_json::to_value(&*event)?;
                        // A dropped stream should stop the reaction quietly
                        // rather than fail the checkpoint forever.
                        let _ = sender.send(StreamItem::Value(value)).await;
                        Ok(())
                    }
                })
                .await;
            if let Err(err) = result {
                log::error!("streaming reaction loop stopped: {err:#}");
            }
        });

        self.base.set_processing_task(task).await;
        self.base.set_status(ComponentStatus::Running, None).await;
        Ok(())
    }

    async fn stop(&self) -> Result<()> {
        self.base.stop_common().await
    }

    async fn status(&self) -> ComponentStatus {
        self.base.get_status().await
    }

    async fn enqueue_query_result(&self, result: QueryResult) -> Result<()> {
        self.base.enqueue_query_result(result).await
    }
}

/// A reaction that hands each query result to a Python callable.
pub struct PythonReaction {
    base: ReactionBase,
    callback: Arc<Py<PyAny>>,
    /// Durable reactions await an async callback and only advance the
    /// checkpoint once it succeeds, so a restart replays anything unhandled.
    durable: bool,
    /// The asyncio loop captured when the reaction was registered.
    ///
    /// The processing loop runs on a tokio worker with no asyncio loop of its
    /// own, so a coroutine has to be scheduled back onto the caller's.
    locals: Option<TaskLocals>,
}

impl PythonReaction {
    pub fn new(id: &str, query_ids: Vec<String>, callback: Py<PyAny>) -> Self {
        Self {
            base: ReactionBase::new(ReactionBaseParams::new(id, query_ids)),
            callback: Arc::new(callback),
            durable: false,
            locals: None,
        }
    }

    pub fn durable(
        id: &str,
        query_ids: Vec<String>,
        callback: Py<PyAny>,
        recovery: ReactionRecoveryPolicy,
        locals: TaskLocals,
    ) -> Self {
        Self {
            base: ReactionBase::new(
                ReactionBaseParams::new(id, query_ids).with_recovery_policy(recovery),
            ),
            callback: Arc::new(callback),
            durable: true,
            locals: Some(locals),
        }
    }
}

/// Invokes the Python callable with the result rendered as a plain dict.
///
/// Runs on a tokio worker thread, so the GIL has to be acquired explicitly.
/// A callback that raises does not advance the checkpoint, matching the
/// contract of `run_standard_loop`.
fn dispatch(callback: &Py<PyAny>, result: &QueryResult) -> Result<()> {
    let payload = serde_json::to_value(result)?;
    Python::attach(|py| -> Result<()> {
        let event = json_to_py(py, &payload)?;
        callback.call1(py, (event,))?;
        Ok(())
    })
}

/// Calls an async Python callback and waits for it to finish.
///
/// Returning an error leaves the checkpoint unadvanced, so the event is
/// retried on restart rather than being lost.
async fn dispatch_async(
    callback: &Py<PyAny>,
    locals: &TaskLocals,
    result: &QueryResult,
) -> Result<()> {
    let payload = serde_json::to_value(result)?;
    let awaitable = Python::attach(|py| -> Result<_> {
        let event = json_to_py(py, &payload)?;
        let returned = callback.call1(py, (event,))?;
        let coroutine = returned.bind(py);
        if !coroutine.hasattr("__await__")? {
            anyhow::bail!(
                "a durable reaction callback must be async; \
                 define it with `async def` or return an awaitable"
            );
        }
        // Scheduled onto the loop captured at registration, since this thread
        // has none of its own.
        Ok(pyo3_async_runtimes::into_future_with_locals(
            locals,
            coroutine.clone(),
        )?)
    })?;
    awaitable.await?;
    Ok(())
}

#[async_trait]
impl Reaction for PythonReaction {
    fn id(&self) -> &str {
        self.base.get_id()
    }

    fn type_name(&self) -> &str {
        PYTHON_COMPONENT_TYPE
    }

    fn properties(&self) -> HashMap<String, Value> {
        HashMap::new()
    }

    fn query_ids(&self) -> Vec<String> {
        self.base.get_queries().to_vec()
    }

    fn auto_start(&self) -> bool {
        self.base.get_auto_start()
    }

    fn is_durable(&self) -> bool {
        self.durable
    }

    async fn initialize(&self, context: ReactionRuntimeContext) {
        self.base.initialize(context).await;
    }

    async fn start(&self) -> Result<()> {
        let shutdown_rx = self.base.create_shutdown_channel().await;
        let checkpoints = self.base.read_all_checkpoints().await.unwrap_or_default();
        let base = self.base.clone_shared();
        let callback = Arc::clone(&self.callback);

        let locals = self.locals.clone();
        let task = tokio::spawn(async move {
            let result = base
                .run_standard_loop(shutdown_rx, checkpoints, move |event| {
                    let callback = Arc::clone(&callback);
                    let locals = locals.clone();
                    async move {
                        match locals {
                            Some(locals) => dispatch_async(&callback, &locals, &event).await,
                            None => dispatch(&callback, &event),
                        }
                    }
                })
                .await;
            if let Err(err) = result {
                log::error!("python reaction loop stopped: {err:#}");
            }
        });

        self.base.set_processing_task(task).await;
        self.base.set_status(ComponentStatus::Running, None).await;
        Ok(())
    }

    async fn stop(&self) -> Result<()> {
        self.base.stop_common().await
    }

    async fn status(&self) -> ComponentStatus {
        self.base.get_status().await
    }

    async fn enqueue_query_result(&self, result: QueryResult) -> Result<()> {
        self.base.enqueue_query_result(result).await
    }
}
