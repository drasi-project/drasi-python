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

use drasi_plugin_sdk::ffi::secret_store::FfiGetSecretResult;
use drasi_plugin_sdk::ffi::FfiStr;
use serde::Deserialize;

/// Host state handed to the resolver callback on every invocation.
pub struct ConfigResolverContext {
    secrets: RwLock<HashMap<String, String>>,
}

impl ConfigResolverContext {
    pub fn new(secrets: HashMap<String, String>) -> Self {
        Self {
            secrets: RwLock::new(secrets),
        }
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
        self.secrets.read().ok()?.get(name).cloned()
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
                "no secret named '{name}' was provided; \
                 pass it to Drasi.create(secrets={{...}})"
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
