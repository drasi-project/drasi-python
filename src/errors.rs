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

//! Error types surfaced to Python.
//!
//! Every failure carries a stable, machine-readable `code` so callers can branch
//! on it instead of matching human-readable messages:
//!
//! ```python
//! try:
//!     await drasi.add_source("nope", "s", {})
//! except DrasiError as err:
//!     if err.code == DrasiErrorCode.UNKNOWN_SOURCE_KIND:
//!         ...
//! ```
//!
//! Unlike the Node.js binding — where napi-rs can only attach a `code` to a
//! synchronous throw, forcing async failures to smuggle the code into the
//! message as `"... [UNKNOWN_SOURCE_KIND]"` — PyO3 raises fully typed
//! exceptions from synchronous and asynchronous paths alike.

use pyo3::exceptions::PyException;
use pyo3::prelude::*;
use pyo3::{create_exception, PyErr};

/// Stable, machine-readable failure codes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DrasiErrorCode {
    UnknownSourceKind,
    UnknownReactionKind,
    UnknownBootstrapKind,
    UnknownSecretStoreKind,
    BootstrapKindRequired,
    MissingConfigField,
    NoPySource,
    PySourceClosed,
    ChangeNotObject,
    ChangeOpRequired,
    ChangeIdRequired,
    RelationRequiresBothEnds,
    UnknownChangeOp,
    StateStorePathRequired,
    UnknownStateStoreKind,
    IndexStorePathRequired,
    UnknownIndexStoreKind,
    IdentityKindRequired,
    UnknownIdentityKind,
    IdentityConfigInvalid,
    DurableRequiresStateStore,
    UnknownQueryLanguage,
    ConfigInvalid,
    PluginSignatureInvalid,
    PluginIncompatible,
    PluginNotFound,
    StreamLagged,
    EngineClosed,
    EngineFailure,
}

impl DrasiErrorCode {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::UnknownSourceKind => "UNKNOWN_SOURCE_KIND",
            Self::UnknownReactionKind => "UNKNOWN_REACTION_KIND",
            Self::UnknownBootstrapKind => "UNKNOWN_BOOTSTRAP_KIND",
            Self::UnknownSecretStoreKind => "UNKNOWN_SECRET_STORE_KIND",
            Self::BootstrapKindRequired => "BOOTSTRAP_KIND_REQUIRED",
            Self::MissingConfigField => "MISSING_CONFIG_FIELD",
            Self::NoPySource => "NO_PY_SOURCE",
            Self::PySourceClosed => "PY_SOURCE_CLOSED",
            Self::ChangeNotObject => "CHANGE_NOT_OBJECT",
            Self::ChangeOpRequired => "CHANGE_OP_REQUIRED",
            Self::ChangeIdRequired => "CHANGE_ID_REQUIRED",
            Self::RelationRequiresBothEnds => "RELATION_REQUIRES_BOTH_ENDS",
            Self::UnknownChangeOp => "UNKNOWN_CHANGE_OP",
            Self::StateStorePathRequired => "STATE_STORE_PATH_REQUIRED",
            Self::UnknownStateStoreKind => "UNKNOWN_STATE_STORE_KIND",
            Self::IndexStorePathRequired => "INDEX_STORE_PATH_REQUIRED",
            Self::UnknownIndexStoreKind => "UNKNOWN_INDEX_STORE_KIND",
            Self::IdentityKindRequired => "IDENTITY_KIND_REQUIRED",
            Self::UnknownIdentityKind => "UNKNOWN_IDENTITY_KIND",
            Self::IdentityConfigInvalid => "IDENTITY_CONFIG_INVALID",
            Self::DurableRequiresStateStore => "DURABLE_REQUIRES_STATE_STORE",
            Self::UnknownQueryLanguage => "UNKNOWN_QUERY_LANGUAGE",
            Self::ConfigInvalid => "CONFIG_INVALID",
            Self::PluginSignatureInvalid => "PLUGIN_SIGNATURE_INVALID",
            Self::PluginIncompatible => "PLUGIN_INCOMPATIBLE",
            Self::PluginNotFound => "PLUGIN_NOT_FOUND",
            Self::StreamLagged => "STREAM_LAGGED",
            Self::EngineClosed => "ENGINE_CLOSED",
            Self::EngineFailure => "ENGINE_FAILURE",
        }
    }

    /// Every code, for building the Python-side `DrasiErrorCode` enum.
    pub fn all() -> &'static [DrasiErrorCode] {
        use DrasiErrorCode::*;
        &[
            UnknownSourceKind,
            UnknownReactionKind,
            UnknownBootstrapKind,
            UnknownSecretStoreKind,
            BootstrapKindRequired,
            MissingConfigField,
            NoPySource,
            PySourceClosed,
            ChangeNotObject,
            ChangeOpRequired,
            ChangeIdRequired,
            RelationRequiresBothEnds,
            UnknownChangeOp,
            StateStorePathRequired,
            UnknownStateStoreKind,
            IndexStorePathRequired,
            UnknownIndexStoreKind,
            IdentityKindRequired,
            UnknownIdentityKind,
            IdentityConfigInvalid,
            DurableRequiresStateStore,
            UnknownQueryLanguage,
            ConfigInvalid,
            PluginSignatureInvalid,
            PluginIncompatible,
            PluginNotFound,
            StreamLagged,
            EngineClosed,
            EngineFailure,
        ]
    }

    /// The exception class this code is raised as.
    fn exception_type(self, py: Python<'_>) -> Py<PyAny> {
        use DrasiErrorCode::*;
        match self {
            UnknownSourceKind
            | UnknownReactionKind
            | UnknownBootstrapKind
            | UnknownSecretStoreKind
            | UnknownStateStoreKind
            | UnknownIndexStoreKind
            | UnknownIdentityKind
            | UnknownQueryLanguage
            | UnknownChangeOp => py.get_type::<UnknownKindError>().into(),

            BootstrapKindRequired
            | MissingConfigField
            | StateStorePathRequired
            | IndexStorePathRequired
            | IdentityKindRequired
            | IdentityConfigInvalid
            | DurableRequiresStateStore
            | ConfigInvalid => py.get_type::<ConfigError>().into(),

            NoPySource
            | PySourceClosed
            | ChangeNotObject
            | ChangeOpRequired
            | ChangeIdRequired
            | RelationRequiresBothEnds => py.get_type::<SourceError>().into(),

            PluginSignatureInvalid => py.get_type::<PluginSignatureError>().into(),
            PluginIncompatible => py.get_type::<PluginCompatibilityError>().into(),
            PluginNotFound => py.get_type::<PluginNotFoundError>().into(),
            StreamLagged => py.get_type::<StreamLaggedError>().into(),
            EngineClosed => py.get_type::<DrasiError>().into(),
            EngineFailure => py.get_type::<DrasiError>().into(),
        }
    }
}

create_exception!(
    _drasi,
    DrasiError,
    PyException,
    "Base class for every error raised by Drasi."
);
create_exception!(_drasi, ConfigError, DrasiError, "Invalid configuration.");
create_exception!(
    _drasi,
    UnknownKindError,
    ConfigError,
    "A source, reaction, bootstrap, store or language kind is not registered."
);
create_exception!(
    _drasi,
    SourceError,
    DrasiError,
    "A change could not be pushed into a Python-defined source."
);
create_exception!(
    _drasi,
    StreamLaggedError,
    DrasiError,
    "A stream dropped items because they were not consumed quickly enough."
);
create_exception!(
    _drasi,
    PluginError,
    DrasiError,
    "A plugin could not be used."
);
create_exception!(
    _drasi,
    PluginNotFoundError,
    PluginError,
    "No plugin matched the requested reference."
);
create_exception!(
    _drasi,
    PluginCompatibilityError,
    PluginError,
    "A plugin is not compatible with this host."
);
create_exception!(
    _drasi,
    PluginSignatureError,
    PluginError,
    "A plugin's signature could not be verified."
);

/// Builds a typed Python exception carrying `code` and `message` attributes.
pub fn error(code: DrasiErrorCode, message: impl Into<String>) -> PyErr {
    let message = message.into();
    Python::attach(|py| {
        let exc_type = code.exception_type(py);
        match exc_type.call1(py, (message.clone(),)) {
            Ok(instance) => {
                if instance.setattr(py, "code", code.as_str()).is_err() {
                    return DrasiError::new_err(message);
                }
                PyErr::from_value(instance.into_bound(py))
            }
            Err(err) => err,
        }
    })
}

/// Maps an engine failure onto [`DrasiErrorCode::EngineFailure`].
pub fn engine_error(err: impl std::fmt::Display) -> PyErr {
    error(DrasiErrorCode::EngineFailure, err.to_string())
}

/// Registers the exception hierarchy and the code constants on the module.
pub fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add("DrasiError", module.py().get_type::<DrasiError>())?;
    module.add("ConfigError", module.py().get_type::<ConfigError>())?;
    module.add(
        "UnknownKindError",
        module.py().get_type::<UnknownKindError>(),
    )?;
    module.add("SourceError", module.py().get_type::<SourceError>())?;
    module.add(
        "StreamLaggedError",
        module.py().get_type::<StreamLaggedError>(),
    )?;
    module.add("PluginError", module.py().get_type::<PluginError>())?;
    module.add(
        "PluginNotFoundError",
        module.py().get_type::<PluginNotFoundError>(),
    )?;
    module.add(
        "PluginCompatibilityError",
        module.py().get_type::<PluginCompatibilityError>(),
    )?;
    module.add(
        "PluginSignatureError",
        module.py().get_type::<PluginSignatureError>(),
    )?;

    let codes: Vec<&'static str> = DrasiErrorCode::all().iter().map(|c| c.as_str()).collect();
    module.add("ERROR_CODES", codes)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    /// PyO3 needs a live interpreter before an exception object can be built.
    fn init() {
        Python::initialize();
    }

    #[test]
    fn every_code_has_a_unique_screaming_snake_name() {
        let mut seen = std::collections::HashSet::new();
        for code in DrasiErrorCode::all() {
            let name = code.as_str();
            assert!(seen.insert(name), "duplicate error code: {name}");
            assert!(
                !name.is_empty()
                    && name
                        .chars()
                        .all(|c| c.is_ascii_uppercase() || c.is_ascii_digit() || c == '_'),
                "{name} is not SCREAMING_SNAKE_CASE"
            );
        }
    }

    /// Every code must reach a real exception class and carry its own code, so
    /// that `except DrasiError as e: e.code` is reliable for all of them.
    #[test]
    fn every_code_builds_an_exception_carrying_its_code_and_message() {
        init();
        Python::attach(|py| {
            let root = py.get_type::<DrasiError>();
            for code in DrasiErrorCode::all() {
                let name = code.as_str();
                let err = error(*code, "boom");
                let value = err.value(py);
                assert!(
                    value.is_instance(root.as_any()).unwrap(),
                    "{name} is not rooted at DrasiError"
                );
                assert_eq!(
                    value.getattr("code").unwrap().extract::<String>().unwrap(),
                    name
                );
                assert_eq!(value.str().unwrap().to_string(), "boom");
            }
        });
    }

    #[test]
    fn an_engine_failure_reports_the_underlying_message() {
        init();
        Python::attach(|py| {
            let err = engine_error("connection refused");
            let value = err.value(py);
            assert_eq!(
                value.getattr("code").unwrap().extract::<String>().unwrap(),
                DrasiErrorCode::EngineFailure.as_str()
            );
            assert_eq!(value.str().unwrap().to_string(), "connection refused");
        });
    }
}
