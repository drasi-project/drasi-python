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

//! Resolving `ConfigValue` references on behalf of plugins.
//!
//! A plugin's configuration can reference a secret or an environment variable
//! instead of carrying the value inline. The plugin cannot read either itself:
//! it serialises the reference to JSON and calls back into the host through a
//! resolver we inject after loading.
//!
//! Two constraints shape this module:
//!
//! * The callback is `extern "C"` and runs on whichever thread the plugin is
//!   on, so nothing here may touch Python.
//! * It may run *on a tokio worker thread*, so it must not block on the async
//!   runtime — doing so panics. The secrets are therefore held in a plain
//!   `std::sync` map and resolution is entirely synchronous.

use std::collections::HashMap;
use std::ffi::c_void;
use std::sync::{Arc, RwLock};

use drasi_lib::secret_store::SecretStoreProvider;
use drasi_plugin_sdk::ffi::secret_store::FfiGetSecretResult;
use drasi_plugin_sdk::ffi::FfiStr;
use serde::Deserialize;

/// A request to the secret store worker.
struct SecretRequest {
    name: String,
    reply: std::sync::mpsc::Sender<Result<String, String>>,
}

/// A plugin-provided secret store, reachable from synchronous code.
///
/// `SecretStoreProvider::get_secret` is async, but the resolver below is a
/// synchronous `extern "C"` callback that may already be running on a tokio
/// worker, where `block_on` panics with "cannot start a runtime from within a
/// runtime". The provider therefore lives on its own thread with its own
/// current-thread runtime, and callers hand it a name and wait on a channel.
struct SecretStoreWorker {
    requests: std::sync::mpsc::Sender<SecretRequest>,
}

impl SecretStoreWorker {
    fn spawn(provider: Box<dyn SecretStoreProvider>) -> std::io::Result<Self> {
        let (requests, incoming) = std::sync::mpsc::channel::<SecretRequest>();
        std::thread::Builder::new()
            .name("drasi-secret-store".to_string())
            .spawn(move || {
                let runtime = match tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                {
                    Ok(runtime) => runtime,
                    Err(err) => {
                        // Answer rather than hang: a caller blocked on the reply
                        // channel would otherwise wait forever.
                        while let Ok(request) = incoming.recv() {
                            let _ = request.reply.send(Err(format!(
                                "the secret store worker could not start a runtime: {err}"
                            )));
                        }
                        return;
                    }
                };
                while let Ok(request) = incoming.recv() {
                    let result = runtime
                        .block_on(provider.get_secret(&request.name))
                        .map_err(|err| err.to_string());
                    let _ = request.reply.send(result);
                }
            })?;
        Ok(Self { requests })
    }

    fn get(&self, name: &str) -> Result<String, String> {
        let (reply, answer) = std::sync::mpsc::channel();
        self.requests
            .send(SecretRequest {
                name: name.to_string(),
                reply,
            })
            .map_err(|_| "the secret store is no longer running".to_string())?;
        answer
            .recv()
            .map_err(|_| "the secret store did not answer".to_string())?
    }
}

/// Host state handed to the resolver callback on every invocation.
pub struct ConfigResolverContext {
    secrets: RwLock<HashMap<String, String>>,
    store: RwLock<Option<SecretStoreWorker>>,
}

impl ConfigResolverContext {
    pub fn new(secrets: HashMap<String, String>) -> Self {
        Self {
            secrets: RwLock::new(secrets),
            store: RwLock::new(None),
        }
    }

    /// Installs a plugin-provided secret store, replacing any previous one.
    pub fn set_secret_store(&self, provider: Box<dyn SecretStoreProvider>) -> anyhow::Result<()> {
        let worker = SecretStoreWorker::spawn(provider)?;
        *self
            .store
            .write()
            .map_err(|_| anyhow::anyhow!("the secret store lock was poisoned"))? = Some(worker);
        Ok(())
    }

    /// Leaks the context for the FFI boundary.
    ///
    /// Deliberately never reclaimed: a loaded plugin can resolve config at any
    /// point in its life, and freeing this while one is still loaded would hand
    /// that plugin a dangling pointer.
    pub fn into_raw(self: Arc<Self>) -> *mut c_void {
        Arc::into_raw(self) as *mut c_void
    }

    fn secret(&self, name: &str) -> Option<String> {
        if let Some(value) = self.secrets.read().ok().and_then(|s| s.get(name).cloned()) {
            return Some(value);
        }

        // Asking the store means blocking this thread on another one, so the
        // answer is cached: a plugin that reads the same reference on every
        // reconnect would otherwise stall a worker every time.
        let value = self.store.read().ok()?.as_ref()?.get(name).ok()?;
        if let Ok(mut secrets) = self.secrets.write() {
            secrets.insert(name.to_string(), value.clone());
        }
        Some(value)
    }
}

/// The reference shapes a plugin can ask us to resolve.
///
/// A plugin serialises `ConfigValue::Secret` as
/// `{"kind":"Secret","name":"DB_PASSWORD"}`.
#[derive(Deserialize)]
#[serde(tag = "kind")]
enum ConfigValueRef {
    Secret {
        name: String,
    },
    EnvironmentVariable {
        name: String,
        #[serde(default)]
        default: Option<String>,
    },
}

/// Resolves one `ConfigValue` reference for a plugin.
///
/// # Safety
///
/// `ctx` must be a pointer produced by [`ConfigResolverContext::into_raw`] and
/// still alive, and `config_value_json` must be valid for the call.
pub extern "C" fn resolve_config_value(
    ctx: *const c_void,
    config_value_json: FfiStr,
) -> FfiGetSecretResult {
    if ctx.is_null() {
        return FfiGetSecretResult::err("the host config resolver was not initialised".to_string());
    }

    // Borrow without taking ownership; the context outlives every call.
    let context = unsafe { &*(ctx as *const ConfigResolverContext) };
    // SAFETY: the plugin passes a valid, NUL-terminated string that outlives
    // this call, per the ConfigResolverFn contract.
    let raw = unsafe { config_value_json.as_str() }.to_string();

    match serde_json::from_str::<ConfigValueRef>(&raw) {
        Ok(ConfigValueRef::Secret { name }) => match context.secret(&name) {
            Some(value) => FfiGetSecretResult::ok(value),
            None => FfiGetSecretResult::err(format!(
                "no secret named '{name}' is available; pass it to \
                 Drasi.create(secrets={{...}}) or install a secret store plugin \
                 and select it with use_secret_store()"
            )),
        },
        Ok(ConfigValueRef::EnvironmentVariable { name, default }) => {
            match std::env::var(&name).ok().or(default) {
                Some(value) => FfiGetSecretResult::ok(value),
                None => FfiGetSecretResult::err(format!(
                    "the environment variable '{name}' is not set and has no default"
                )),
            }
        }
        Err(err) => FfiGetSecretResult::err(format!(
            "could not understand the config value reference {raw:?}: {err}"
        )),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn context() -> ConfigResolverContext {
        ConfigResolverContext::new(HashMap::from([("DB_PASSWORD".into(), "hunter2".into())]))
    }

    #[test]
    fn resolves_a_known_secret() {
        assert_eq!(context().secret("DB_PASSWORD").as_deref(), Some("hunter2"));
    }

    #[test]
    fn reports_an_unknown_secret_as_missing() {
        assert_eq!(context().secret("NOPE"), None);
    }

    #[test]
    fn parses_the_reference_shapes_a_plugin_sends() {
        let secret: ConfigValueRef =
            serde_json::from_str(r#"{"kind":"Secret","name":"DB_PASSWORD"}"#).unwrap();
        assert!(matches!(secret, ConfigValueRef::Secret { name } if name == "DB_PASSWORD"));

        let env: ConfigValueRef = serde_json::from_str(
            r#"{"kind":"EnvironmentVariable","name":"PORT","default":"5432"}"#,
        )
        .unwrap();
        match env {
            ConfigValueRef::EnvironmentVariable { name, default } => {
                assert_eq!(name, "PORT");
                assert_eq!(default.as_deref(), Some("5432"));
            }
            _ => panic!("expected an environment variable reference"),
        }
    }

    #[test]
    fn an_environment_variable_may_omit_its_default() {
        let env: ConfigValueRef =
            serde_json::from_str(r#"{"kind":"EnvironmentVariable","name":"PORT"}"#).unwrap();
        assert!(matches!(
            env,
            ConfigValueRef::EnvironmentVariable { default: None, .. }
        ));
    }
}
