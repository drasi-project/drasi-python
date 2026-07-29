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

//! Loading, discovering and installing Drasi plugins.
//!
//! A plugin is a platform-specific cdylib published as an OCI artifact. Because
//! it is native code loaded into this process, only a build matching this host's
//! Drasi versions and target triple can be used — see `docs/plugins.md`.

use std::collections::HashMap;
use std::ffi::c_void;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;

use anyhow::{anyhow, Context, Result};
use drasi_host_sdk::callbacks::{instance_lifecycle_callback_fn, instance_log_callback_fn};
use drasi_host_sdk::lockfile::{compute_file_hash, LockedPlugin, PluginLockfile};
use drasi_host_sdk::plugin_types::PluginFileEvent;
use drasi_host_sdk::registry::cosign::{
    CosignVerifier, SignatureStatus, TrustedIdentity, VerificationConfig,
};
use drasi_host_sdk::registry::oci::OciRegistryClient;
use drasi_host_sdk::registry::platform::target_triple_to_arch_suffix;
use drasi_host_sdk::registry::resolver::PluginResolver;
use drasi_host_sdk::registry::types::{HostVersionInfo, RegistryConfig};
use drasi_host_sdk::watcher::{PluginWatcher, PluginWatcherConfig};
use drasi_host_sdk::{
    InstanceCallbackContext, LoadedPlugin, PluginLoader, PluginLoaderConfig, PluginRegistry,
    DEFAULT_PLUGIN_FILE_PATTERNS,
};
use drasi_lib::DrasiLib;
use drasi_plugin_sdk::descriptor::{
    BootstrapPluginDescriptor, ReactionPluginDescriptor, SecretStorePluginDescriptor,
    SourcePluginDescriptor,
};
use serde_json::Value;
use tokio::sync::Mutex;

use crate::host::{ffi_sdk_version, target_triple};
use crate::secrets::{resolve_config_value, ConfigResolverContext};
use crate::{DRASI_CORE_VERSION, DRASI_LIB_VERSION, DRASI_SDK_VERSION};

/// The registry official Drasi plugins are published to.
pub const DEFAULT_REGISTRY: &str = "ghcr.io/drasi-project";

/// Counts returned after scanning a directory.
#[derive(Debug, Default, Clone, Copy)]
pub struct LoadSummary {
    pub plugins: usize,
    pub sources: usize,
    pub reactions: usize,
    pub bootstrap: usize,
    pub secret_stores: usize,
    pub identity_providers: usize,
}

/// What a plugin reference resolved to.
#[derive(Debug, Clone)]
pub struct Resolved {
    pub reference: String,
    pub kind: String,
    pub plugin_type: String,
    pub version: String,
    pub target_triple: String,
    pub sdk_version: String,
    pub core_version: String,
    pub lib_version: String,
}

/// A raw callback pointer handed across the FFI boundary.
///
/// The pointer is an `Arc<InstanceCallbackContext>` produced by `into_raw`, and
/// that type is `Send + Sync`, so the pointer is safe to move between threads.
/// Wrapping it keeps futures that hold one `Send`.
#[derive(Clone, Copy)]
struct CallbackPtr(*mut c_void);

// SAFETY: see the type's documentation.
unsafe impl Send for CallbackPtr {}
unsafe impl Sync for CallbackPtr {}

/// Owns everything needed to load plugins into one engine instance.
///
/// The loaded libraries are retained for the lifetime of the host: a plugin's
/// descriptors hold function pointers into its cdylib, so dropping the library
/// would leave them dangling.
pub struct PluginHost {
    /// Context pointer injected into every loaded plugin so it can resolve
    /// secret and environment-variable references in its own config. The
    /// backing `Arc` is intentionally leaked, since a plugin may resolve at any
    /// point in its life.
    resolver_ctx: CallbackPtr,
    /// The same context the pointer above refers to, kept so the host can
    /// install a secret store after plugins have been loaded.
    resolver: Arc<ConfigResolverContext>,
    registry: Mutex<PluginRegistry>,
    loaded: Mutex<Vec<LoadedPlugin>>,
    callbacks: Mutex<Option<Arc<InstanceCallbackContext>>>,
    /// Raw pointers handed to plugins, retained so they stay valid for as long
    /// as a loaded plugin might invoke them.
    callback_ptrs: std::sync::Mutex<Vec<CallbackPtr>>,
    /// What has been installed, so a lockfile can record it.
    installed: Mutex<Vec<LockedPlugin>>,
}

impl PluginHost {
    pub fn new(secrets: HashMap<String, String>) -> Self {
        let resolver = Arc::new(ConfigResolverContext::new(secrets));
        Self {
            resolver_ctx: CallbackPtr(Arc::clone(&resolver).into_raw()),
            resolver,
            registry: Mutex::new(PluginRegistry::new()),
            loaded: Mutex::new(Vec::new()),
            callbacks: Mutex::new(None),
            callback_ptrs: std::sync::Mutex::new(Vec::new()),
            installed: Mutex::new(Vec::new()),
        }
    }

    /// The version and platform information plugins are matched against.
    pub fn host_info() -> HostVersionInfo {
        HostVersionInfo {
            sdk_version: DRASI_SDK_VERSION.to_string(),
            core_version: DRASI_CORE_VERSION.to_string(),
            lib_version: DRASI_LIB_VERSION.to_string(),
            target_triple: target_triple().to_string(),
        }
    }

    async fn callback_context(
        &self,
        core: &DrasiLib,
        instance_id: &str,
    ) -> Arc<InstanceCallbackContext> {
        let mut guard = self.callbacks.lock().await;
        if let Some(existing) = guard.as_ref() {
            return Arc::clone(existing);
        }
        let update_tx = core.component_graph().read().await.update_sender();
        let context = Arc::new(InstanceCallbackContext {
            instance_id: instance_id.to_string(),
            runtime_handle: tokio::runtime::Handle::current(),
            log_registry: core.log_registry(),
            update_tx,
        });
        *guard = Some(Arc::clone(&context));
        context
    }

    /// Leaks a pair of context pointers for the loader to hand to plugins.
    ///
    /// They are recorded so they outlive every plugin that might call back into
    /// the host. Reclaiming them while a plugin is still loaded would leave the
    /// plugin holding a dangling context.
    async fn callback_pointers(
        &self,
        core: &DrasiLib,
        instance_id: &str,
    ) -> (CallbackPtr, CallbackPtr) {
        let context = self.callback_context(core, instance_id).await;
        let log_ctx = CallbackPtr(Arc::clone(&context).into_raw());
        let lifecycle_ctx = CallbackPtr(Arc::clone(&context).into_raw());
        if let Ok(mut recorded) = self.callback_ptrs.lock() {
            recorded.extend([log_ctx, lifecycle_ctx]);
        }
        (log_ctx, lifecycle_ctx)
    }

    /// Discovers and loads every plugin in `dir`.
    ///
    /// When `expected_hashes` is supplied, a file is only loaded if its SHA-256
    /// matches the entry recorded for its filename. Files with no entry are
    /// skipped, so the map acts as an allowlist rather than a filter.
    pub async fn load_dir(
        &self,
        core: &DrasiLib,
        instance_id: &str,
        dir: &Path,
        expected_hashes: Option<&HashMap<String, String>>,
    ) -> Result<LoadSummary> {
        if !dir.is_dir() {
            return Err(anyhow!("plugin directory not found: {}", dir.display()));
        }

        let (log_ctx, lifecycle_ctx) = self.callback_pointers(core, instance_id).await;

        let loader = PluginLoader::new(PluginLoaderConfig {
            plugin_dir: dir.to_path_buf(),
            file_patterns: DEFAULT_PLUGIN_FILE_PATTERNS
                .iter()
                .map(|pattern| (*pattern).to_string())
                .collect(),
        });

        let plugins = match expected_hashes {
            None => loader.load_all(
                log_ctx.0,
                instance_log_callback_fn(),
                lifecycle_ctx.0,
                instance_lifecycle_callback_fn(),
            )?,
            Some(expected) => {
                let mut plugins = Vec::new();
                for path in verified_candidates(dir, expected)? {
                    match loader.load_plugin(
                        &path,
                        log_ctx.0,
                        instance_log_callback_fn(),
                        lifecycle_ctx.0,
                        instance_lifecycle_callback_fn(),
                    ) {
                        Ok(plugin) => plugins.push(plugin),
                        Err(err) => log::warn!("skipping {}: {err:#}", path.display()),
                    }
                }
                plugins
            }
        };

        self.register(plugins).await
    }

    /// Loads a single plugin file.
    pub async fn load_file(
        &self,
        core: &DrasiLib,
        instance_id: &str,
        path: &Path,
    ) -> Result<LoadSummary> {
        let (log_ctx, lifecycle_ctx) = self.callback_pointers(core, instance_id).await;

        let directory = path.parent().unwrap_or(Path::new(".")).to_path_buf();
        let loader = PluginLoader::new(PluginLoaderConfig {
            plugin_dir: directory,
            file_patterns: DEFAULT_PLUGIN_FILE_PATTERNS
                .iter()
                .map(|pattern| (*pattern).to_string())
                .collect(),
        });

        let plugin = loader
            .load_plugin(
                path,
                log_ctx.0,
                instance_log_callback_fn(),
                lifecycle_ctx.0,
                instance_lifecycle_callback_fn(),
            )
            .with_context(|| format!("failed to load {}", path.display()))?;

        self.register(vec![plugin]).await
    }

    /// Registers the descriptors from freshly loaded plugins.
    async fn register(&self, mut plugins: Vec<LoadedPlugin>) -> Result<LoadSummary> {
        let mut summary = LoadSummary {
            plugins: plugins.len(),
            ..Default::default()
        };

        let mut registry = self.registry.lock().await;
        for plugin in &mut plugins {
            // The proxies are not clonable, so move them out of the loaded
            // plugin. The `LoadedPlugin` itself is retained below to keep the
            // underlying library — and therefore these function pointers — alive.
            for descriptor in std::mem::take(&mut plugin.source_plugins) {
                registry.register_source(Arc::new(descriptor));
                summary.sources += 1;
            }
            for descriptor in std::mem::take(&mut plugin.reaction_plugins) {
                registry.register_reaction(Arc::new(descriptor));
                summary.reactions += 1;
            }
            for descriptor in std::mem::take(&mut plugin.bootstrap_plugins) {
                registry.register_bootstrapper(Arc::new(descriptor));
                summary.bootstrap += 1;
            }
            // Dropping these silently is what made `install_plugin` report a
            // secret store as loaded and then behave as though it were absent.
            for descriptor in std::mem::take(&mut plugin.secret_store_plugins) {
                registry.register_secret_store(Arc::new(descriptor));
                summary.secret_stores += 1;
            }
            for descriptor in std::mem::take(&mut plugin.identity_provider_plugins) {
                registry.register_identity_provider(Arc::new(descriptor));
                summary.identity_providers += 1;
            }
        }
        drop(registry);

        // A plugin cannot read a secret itself; it calls back through this.
        // Injecting before the descriptors are used means the very first
        // component created from them can already resolve references.
        for plugin in &plugins {
            plugin.inject_config_resolver(self.resolver_ctx.0, resolve_config_value);
        }

        // Keep the libraries alive; the registered descriptors point into them.
        self.loaded.lock().await.extend(plugins);
        Ok(summary)
    }

    pub async fn source_kinds(&self) -> Vec<String> {
        self.registry
            .lock()
            .await
            .source_kinds()
            .into_iter()
            .map(str::to_string)
            .collect()
    }

    pub async fn reaction_kinds(&self) -> Vec<String> {
        self.registry
            .lock()
            .await
            .reaction_kinds()
            .into_iter()
            .map(str::to_string)
            .collect()
    }

    pub async fn bootstrap_kinds(&self) -> Vec<String> {
        self.registry
            .lock()
            .await
            .bootstrapper_kinds()
            .into_iter()
            .map(str::to_string)
            .collect()
    }

    /// Routes plugin secret references through a plugin-provided store.
    pub fn set_secret_store(
        &self,
        provider: Box<dyn drasi_lib::secret_store::SecretStoreProvider>,
    ) -> anyhow::Result<()> {
        self.resolver.set_secret_store(provider)
    }

    pub async fn secret_store_kinds(&self) -> Vec<String> {
        self.registry
            .lock()
            .await
            .secret_store_kinds()
            .into_iter()
            .map(str::to_string)
            .collect()
    }

    pub async fn identity_kinds(&self) -> Vec<String> {
        self.registry
            .lock()
            .await
            .identity_provider_kinds()
            .into_iter()
            .map(str::to_string)
            .collect()
    }

    pub async fn secret_store_descriptor(
        &self,
        kind: &str,
    ) -> Option<Arc<dyn SecretStorePluginDescriptor>> {
        self.registry.lock().await.get_secret_store(kind).cloned()
    }

    pub async fn source_descriptor(&self, kind: &str) -> Option<Arc<dyn SourcePluginDescriptor>> {
        self.registry.lock().await.get_source(kind).cloned()
    }

    pub async fn reaction_descriptor(
        &self,
        kind: &str,
    ) -> Option<Arc<dyn ReactionPluginDescriptor>> {
        self.registry.lock().await.get_reaction(kind).cloned()
    }

    pub async fn bootstrap_descriptor(
        &self,
        kind: &str,
    ) -> Option<Arc<dyn BootstrapPluginDescriptor>> {
        self.registry.lock().await.get_bootstrapper(kind).cloned()
    }
}

impl PluginHost {
    /// Records an installed plugin so `write_lockfile` can pin it later.
    pub async fn record_install(&self, resolved: &Resolved, path: &Path) {
        let digest = resolved
            .reference
            .split_once('@')
            .map(|(_, digest)| digest.to_string())
            .unwrap_or_default();
        let entry = LockedPlugin {
            reference: resolved.reference.clone(),
            version: resolved.version.clone(),
            digest,
            sdk_version: resolved.sdk_version.clone(),
            core_version: resolved.core_version.clone(),
            lib_version: resolved.lib_version.clone(),
            platform: resolved.target_triple.clone(),
            filename: path
                .file_name()
                .map(|name| name.to_string_lossy().into_owned())
                .unwrap_or_default(),
            file_hash: compute_file_hash(path).ok(),
            git_commit: None,
            build_timestamp: None,
            signature: None,
        };
        self.installed.lock().await.push(entry);
    }

    /// Writes a lockfile pinning everything installed in this session.
    pub async fn write_lockfile(&self, dir: &Path) -> Result<usize> {
        let installed = self.installed.lock().await;
        if installed.is_empty() {
            return Err(anyhow!(
                "nothing has been installed in this session, so there is nothing to pin"
            ));
        }
        let mut lockfile = PluginLockfile::new();
        for entry in installed.iter() {
            lockfile.insert(entry.reference.clone(), entry.clone());
        }
        lockfile.write(dir)?;
        Ok(installed.len())
    }

    /// Reads a lockfile, returning the pinned references.
    pub fn read_lockfile(dir: &Path) -> Result<Vec<LockedPlugin>> {
        let lockfile = PluginLockfile::read(dir)?
            .ok_or_else(|| anyhow!("no plugins.lock found in {}", dir.display()))?;
        Ok(lockfile.iter().map(|(_, entry)| entry.clone()).collect())
    }

    /// Watches `dir` and loads plugins as they appear.
    ///
    /// Returns once watching has started; loading continues in the background.
    /// A file that fails to load is logged and skipped, since a half-written
    /// file being copied in is a normal transient state.
    pub async fn watch(
        self: &Arc<Self>,
        core: DrasiLib,
        instance_id: String,
        dir: PathBuf,
        debounce: Duration,
    ) -> Result<()> {
        let mut watcher = PluginWatcher::new(PluginWatcherConfig {
            plugins_dir: dir.clone(),
            debounce,
        });
        let mut events = watcher.subscribe();
        watcher.start()?;

        let host = Arc::clone(self);
        tokio::spawn(async move {
            // Keep the watcher alive for as long as we are listening; dropping
            // it stops the underlying filesystem notifier.
            let _watcher = watcher;
            loop {
                match events.recv().await {
                    Ok(PluginFileEvent::Added(path)) | Ok(PluginFileEvent::Changed(path)) => {
                        if let Err(err) = host.load_file(&core, &instance_id, &path).await {
                            log::warn!("watched plugin {} was not loaded: {err:#}", path.display());
                        }
                    }
                    // A loaded cdylib cannot be unloaded safely, so a removal
                    // leaves the already-registered kinds in place.
                    Ok(PluginFileEvent::Removed(path)) => {
                        log::info!("watched plugin {} was removed", path.display());
                    }
                    Err(tokio::sync::broadcast::error::RecvError::Lagged(count)) => {
                        log::warn!("missed {count} plugin file event(s)");
                    }
                    Err(tokio::sync::broadcast::error::RecvError::Closed) => return,
                }
            }
        });
        Ok(())
    }
}

/// Returns the plugin files in `dir` whose SHA-256 matches the expected map.
fn verified_candidates(dir: &Path, expected: &HashMap<String, String>) -> Result<Vec<PathBuf>> {
    let mut accepted = Vec::new();
    for entry in std::fs::read_dir(dir)? {
        let path = entry?.path();
        if !path.is_file() {
            continue;
        }
        let Some(name) = path.file_name().and_then(|name| name.to_str()) else {
            continue;
        };
        let Some(want) = expected.get(name) else {
            log::warn!("skipping {name}: no expected hash was provided");
            continue;
        };
        let actual = compute_file_hash(&path)?;
        if actual.eq_ignore_ascii_case(want) {
            accepted.push(path);
        } else {
            log::warn!("skipping {name}: sha256 {actual} does not match the expected {want}");
        }
    }
    Ok(accepted)
}

/// Builds an OCI client, optionally with signature verification enabled.
pub fn registry_client(trusted: Vec<(String, String)>, verify: bool) -> OciRegistryClient {
    let config = RegistryConfig {
        default_registry: DEFAULT_REGISTRY.to_string(),
        ..Default::default()
    };
    if !verify {
        return OciRegistryClient::new(config);
    }

    let identities: Vec<TrustedIdentity> = trusted
        .into_iter()
        .map(|(issuer, subject_pattern)| TrustedIdentity {
            issuer,
            subject_pattern,
        })
        .collect();
    let verification = VerificationConfig {
        trusted_identities: identities,
        ..Default::default()
    };
    OciRegistryClient::with_verifier(config, CosignVerifier::new(verification))
}

/// Resolves a reference to the newest build compatible with this host.
///
/// `reference` may be a short form such as `source/mock`, a versioned form such
/// as `source/mock:0.2.7`, or a fully qualified reference including the
/// architecture suffix. Resolution accounts for the host's target triple, so a
/// caller never has to know that plugins are published per platform.
pub async fn resolve(client: &OciRegistryClient, reference: &str) -> Result<Resolved> {
    let host = PluginHost::host_info();
    let resolver = PluginResolver::new(client, &host);
    let resolved = resolver
        .resolve(reference, DEFAULT_REGISTRY)
        .await
        .with_context(|| {
            format!(
                "no build of '{reference}' is compatible with this host \
                 (target {}, sdk {}, core {}, lib {})",
                host.target_triple, host.sdk_version, host.core_version, host.lib_version
            )
        })?;

    let metadata = client.fetch_metadata(&resolved.reference).await?;
    Ok(Resolved {
        reference: resolved.reference,
        kind: metadata.kind,
        plugin_type: metadata.plugin_type,
        version: metadata.version,
        target_triple: metadata.target_triple,
        sdk_version: metadata.sdk_version,
        core_version: metadata.core_version,
        lib_version: metadata.lib_version,
    })
}

/// The file name a plugin should be written to on this platform.
///
/// The loader discovers plugins by filename, so the prefix and extension have
/// to match the host's conventions: `libdrasi_source_mock.dylib` on macOS,
/// `drasi_source_mock.dll` on Windows.
pub fn plugin_file_name(plugin_type: &str, kind: &str) -> String {
    let stem = format!("drasi_{}_{}", plugin_type, kind.replace('-', "_"));
    if cfg!(target_os = "windows") {
        format!("{stem}.dll")
    } else if cfg!(target_os = "macos") {
        format!("lib{stem}.dylib")
    } else {
        format!("lib{stem}.so")
    }
}

/// A human-readable form of a verification outcome.
pub fn signature_status(status: &SignatureStatus) -> &'static str {
    match status {
        SignatureStatus::Verified { .. } => "verified",
        SignatureStatus::Tampered { .. } => "tampered",
        _ => "unsigned",
    }
}

/// The architecture suffix used by tags for this host, if it is a published one.
pub fn host_arch_suffix() -> Option<String> {
    target_triple_to_arch_suffix(target_triple())
}

/// Index backends compiled into this build.
///
/// RocksDB is behind a Cargo feature, so whether it is available depends on how
/// the wheel was built. Reporting it lets callers — and tests — ask the build
/// rather than guess from an environment variable.
pub fn index_backends() -> Vec<&'static str> {
    let mut backends = vec!["memory"];
    if cfg!(feature = "rocksdb") {
        backends.push("rocksdb");
    }
    backends
}

/// A description of this host, for error messages and diagnostics.
pub fn describe_host() -> Value {
    serde_json::json!({
        "target_triple": target_triple(),
        "arch_suffix": host_arch_suffix(),
        "ffi_sdk_version": ffi_sdk_version(),
        "sdk_version": DRASI_SDK_VERSION,
        "core_version": DRASI_CORE_VERSION,
        "lib_version": DRASI_LIB_VERSION,
        "index_backends": index_backends(),
    })
}

/// The SHA-256 of a file on disk.
pub fn file_hash(path: &Path) -> Result<String> {
    compute_file_hash(path)
}
