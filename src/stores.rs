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

//! Optional backing stores and credentials supplied when creating an engine.
//!
//! All four are optional. Without them the engine keeps secrets, plugin state
//! and query indexes in memory, which is fine for tests and short-lived
//! processes but loses everything on restart.

use std::collections::HashMap;
use std::sync::Arc;

use drasi_lib::builder::DrasiLibBuilder;
use drasi_lib::identity::{ApplicationIdentityProvider, Credentials, PasswordIdentityProvider};
use drasi_lib::secret_store::MemorySecretStoreProvider;
use pyo3::prelude::*;
use pyo3::types::{PyAnyMethods, PyDict};
use serde_json::Value;

use crate::conversions::py_to_json;
use crate::errors::{error, DrasiErrorCode};

/// The optional stores and credentials an engine can be built with.
#[derive(Default)]
pub struct CreateOptions {
    pub secrets: HashMap<String, String>,
    pub state_store: Option<StateStore>,
    pub index_store: Option<IndexStore>,
    pub identity: Option<Identity>,
}

pub struct StateStore {
    pub path: String,
}

pub struct IndexStore {
    /// Passed to the backend descriptor untouched; the keys are its own.
    /// Only read when a backend is compiled in.
    #[cfg_attr(not(feature = "rocksdb"), allow(dead_code))]
    pub config: Value,
}

pub enum Identity {
    Password {
        username: String,
        password: String,
    },
    Token {
        username: String,
        token: String,
    },
    /// Supplied by an `identity/*` plugin rather than built into the engine.
    Plugin {
        kind: String,
        config: serde_json::Value,
    },
}

fn required<'py>(
    options: &Bound<'py, PyDict>,
    key: &str,
    code: DrasiErrorCode,
    what: &str,
) -> PyResult<String> {
    options
        .get_item(key)?
        .filter(|value| !value.is_none())
        .ok_or_else(|| error(code, what.to_string()))?
        .extract()
        .map_err(|_| error(code, format!("{what} (it must be a string)")))
}

impl CreateOptions {
    /// Parses the keyword arguments accepted by `Drasi.create`.
    pub fn parse(
        secrets: Option<HashMap<String, String>>,
        state_store: Option<&Bound<'_, PyAny>>,
        index_store: Option<&Bound<'_, PyAny>>,
        identity: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Self> {
        Ok(Self {
            secrets: secrets.unwrap_or_default(),
            state_store: state_store.map(parse_state_store).transpose()?,
            index_store: index_store.map(parse_index_store).transpose()?,
            identity: identity.map(parse_identity).transpose()?,
        })
    }

    /// Whether a durable state store was configured.
    ///
    /// Durable reactions need one, since their checkpoints have to survive a
    /// restart to be worth anything.
    pub fn has_state_store(&self) -> bool {
        self.state_store.is_some()
    }

    /// Applies the options to a builder, returning the secrets for the plugin
    /// config resolver.
    ///
    /// The engine's own secret store and the plugin-facing resolver are fed
    /// from the same map, but are separate objects: the resolver runs on plugin
    /// threads and must not touch the async runtime.
    /// The identity plugin this configuration asks for, if any.
    ///
    /// Resolving it needs a loaded plugin, which is why the caller does it and
    /// hands the result back to `apply`.
    pub fn identity_plugin(&self) -> Option<(String, serde_json::Value)> {
        match &self.identity {
            Some(Identity::Plugin { kind, config }) => Some((kind.clone(), config.clone())),
            _ => None,
        }
    }

    pub async fn apply(
        mut self,
        mut builder: DrasiLibBuilder,
        plugin_identity: Option<Arc<dyn drasi_lib::identity::IdentityProvider>>,
    ) -> PyResult<(DrasiLibBuilder, HashMap<String, String>)> {
        let secrets = std::mem::take(&mut self.secrets);
        let mut store = MemorySecretStoreProvider::new();
        for (name, value) in &secrets {
            store = store.with_secret(name.clone(), value.clone());
        }
        builder = builder.with_secret_store_provider(Arc::new(store));

        if let Some(state_store) = self.state_store {
            let provider = drasi_state_store_redb::RedbStateStoreProvider::new(&state_store.path)
                .map_err(|err| {
                error(
                    DrasiErrorCode::ConfigInvalid,
                    format!(
                        "could not open the redb state store at '{}': {err}",
                        state_store.path
                    ),
                )
            })?;
            builder = builder.with_state_store_provider(Arc::new(provider));
        }

        if let Some(index_store) = self.index_store {
            builder = apply_index_store(builder, index_store).await?;
        }

        if let Some(identity) = self.identity {
            let provider: Arc<dyn drasi_lib::identity::IdentityProvider> = match identity {
                Identity::Password { username, password } => {
                    Arc::new(PasswordIdentityProvider::new(username, password))
                }
                Identity::Token { username, token } => {
                    // drasi-lib has no built-in token provider, so serve the
                    // fixed credential through the application provider.
                    Arc::new(ApplicationIdentityProvider::new_sync(move |_| {
                        Ok(Credentials::Token {
                            username: username.clone(),
                            token: token.clone(),
                        })
                    }))
                }
                Identity::Plugin { kind, .. } => plugin_identity.ok_or_else(|| {
                    error(
                        DrasiErrorCode::UnknownIdentityKind,
                        format!(
                            "no identity plugin registered for kind '{kind}'; \
                             pass plugins_dir= to create() with the plugin in it"
                        ),
                    )
                })?,
            };
            builder = builder.with_identity_provider(provider);
        }

        Ok((builder, secrets))
    }
}

#[cfg(feature = "rocksdb")]
async fn apply_index_store(
    builder: DrasiLibBuilder,
    index_store: IndexStore,
) -> PyResult<DrasiLibBuilder> {
    use drasi_index_rocksdb::RocksDbIndexDescriptor;
    use drasi_plugin_sdk::descriptor::IndexBackendPluginDescriptor;

    // Awaited rather than blocked on: this runs on a tokio worker thread, and
    // blocking there panics with "cannot start a runtime from within a runtime".
    let provider = RocksDbIndexDescriptor
        .create_index_backend(&index_store.config)
        .await
        .map_err(|err| {
            error(
                DrasiErrorCode::ConfigInvalid,
                format!("could not open the RocksDB index store: {err}"),
            )
        })?;
    Ok(builder.with_default_index_provider("rocksdb", provider))
}

#[cfg(not(feature = "rocksdb"))]
async fn apply_index_store(
    _builder: DrasiLibBuilder,
    _index_store: IndexStore,
) -> PyResult<DrasiLibBuilder> {
    Err(error(
        DrasiErrorCode::UnknownIndexStoreKind,
        "this build has no index store backends; \
         rebuild with the 'rocksdb' Cargo feature enabled",
    ))
}

fn parse_state_store(value: &Bound<'_, PyAny>) -> PyResult<StateStore> {
    let options = value.cast::<PyDict>().map_err(|_| {
        error(
            DrasiErrorCode::ConfigInvalid,
            "'state_store' must be a mapping",
        )
    })?;

    let kind = required(
        options,
        "kind",
        DrasiErrorCode::UnknownStateStoreKind,
        "'state_store' requires a 'kind'",
    )?;
    if kind != "redb" {
        return Err(error(
            DrasiErrorCode::UnknownStateStoreKind,
            format!("unknown state store kind '{kind}', expected 'redb'"),
        ));
    }

    Ok(StateStore {
        path: required(
            options,
            "path",
            DrasiErrorCode::StateStorePathRequired,
            "a redb state store requires a 'path'",
        )?,
    })
}

fn parse_index_store(value: &Bound<'_, PyAny>) -> PyResult<IndexStore> {
    let options = value.cast::<PyDict>().map_err(|_| {
        error(
            DrasiErrorCode::ConfigInvalid,
            "'index_store' must be a mapping",
        )
    })?;

    let kind = required(
        options,
        "kind",
        DrasiErrorCode::UnknownIndexStoreKind,
        "'index_store' requires a 'kind'",
    )?;
    if kind != "rocksdb" {
        return Err(error(
            DrasiErrorCode::UnknownIndexStoreKind,
            format!("unknown index store kind '{kind}', expected 'rocksdb'"),
        ));
    }
    if options.get_item("path")?.is_none_or(|path| path.is_none()) {
        return Err(error(
            DrasiErrorCode::IndexStorePathRequired,
            "a rocksdb index store requires a 'path'",
        ));
    }

    // The backend owns its config schema, so pass the mapping through and let
    // it reject anything it does not understand.
    let mut config = py_to_json(value)?;
    if let Value::Object(fields) = &mut config {
        fields.remove("kind");
        rename(fields, "enable_archive", "enableArchive");
        rename(fields, "direct_io", "directIo");
    }
    Ok(IndexStore { config })
}

/// Accepts the snake_case spelling for a backend key that is camelCase.
fn rename(fields: &mut serde_json::Map<String, Value>, from: &str, to: &str) {
    if let Some(value) = fields.remove(from) {
        fields.entry(to.to_string()).or_insert(value);
    }
}

fn parse_identity(value: &Bound<'_, PyAny>) -> PyResult<Identity> {
    let options = value.cast::<PyDict>().map_err(|_| {
        error(
            DrasiErrorCode::ConfigInvalid,
            "'identity' must be a mapping",
        )
    })?;

    let kind = required(
        options,
        "kind",
        DrasiErrorCode::IdentityKindRequired,
        "'identity' requires a 'kind'",
    )?;

    match kind.as_str() {
        "password" => Ok(Identity::Password {
            username: required(
                options,
                "username",
                DrasiErrorCode::IdentityConfigInvalid,
                "a password identity requires a 'username'",
            )?,
            password: required(
                options,
                "password",
                DrasiErrorCode::IdentityConfigInvalid,
                "a password identity requires a 'password'",
            )?,
        }),
        "token" => Ok(Identity::Token {
            // A token is often issued for a specific principal, but not always.
            username: options
                .get_item("username")?
                .filter(|value| !value.is_none())
                .map(|value| value.extract())
                .transpose()?
                .unwrap_or_default(),
            token: required(
                options,
                "token",
                DrasiErrorCode::IdentityConfigInvalid,
                "a token identity requires a 'token'",
            )?,
        }),
        // Anything else names an identity plugin. Whether one is registered
        // for that kind is decided once plugins have been loaded, because at
        // this point none have been.
        other => {
            let mut config = py_to_json(options.as_any())?;
            if let Some(map) = config.as_object_mut() {
                map.remove("kind");
            }
            Ok(Identity::Plugin {
                kind: other.to_string(),
                config,
            })
        }
    }
}
