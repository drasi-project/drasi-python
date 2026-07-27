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

//! Conversions between Python objects and the Drasi data model.
//!
//! The Python API is snake_case throughout, but the camelCase spellings used by
//! the Node.js binding are accepted on input so that examples and configuration
//! can be moved between the two without editing.

use std::sync::Arc;

use drasi_core::models::{
    Element, ElementMetadata, ElementPropertyMap, ElementReference, SourceChange,
};
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyDict, PyFloat, PyInt, PyList, PyMapping, PySequence, PyString};
use serde_json::{Map, Value};

use crate::errors::{error, DrasiErrorCode};

/// Accepted spellings for the start of a relation, in precedence order.
const START_ID_KEYS: &[&str] = &["start_id", "startId", "in_id", "inId"];
/// Accepted spellings for the end of a relation, in precedence order.
const END_ID_KEYS: &[&str] = &["end_id", "endId", "out_id", "outId"];
const EFFECTIVE_FROM_KEYS: &[&str] = &["effective_from", "effectiveFrom"];

/// Converts a Python object into a `serde_json::Value`.
pub fn py_to_json(value: &Bound<'_, PyAny>) -> PyResult<Value> {
    if value.is_none() {
        return Ok(Value::Null);
    }
    // `bool` must precede `int`: Python's bool is a subclass of int.
    if let Ok(flag) = value.cast::<PyBool>() {
        return Ok(Value::Bool(flag.is_true()));
    }
    if let Ok(text) = value.cast::<PyString>() {
        return Ok(Value::String(text.to_cow()?.into_owned()));
    }
    if value.cast::<PyInt>().is_ok() {
        if let Ok(number) = value.extract::<i64>() {
            return Ok(Value::from(number));
        }
        if let Ok(number) = value.extract::<u64>() {
            return Ok(Value::from(number));
        }
        return Err(error(
            DrasiErrorCode::ConfigInvalid,
            "integer is out of range for a JSON number",
        ));
    }
    if value.cast::<PyFloat>().is_ok() {
        let number = value.extract::<f64>()?;
        return serde_json::Number::from_f64(number)
            .map(Value::Number)
            .ok_or_else(|| {
                error(
                    DrasiErrorCode::ConfigInvalid,
                    format!("{number} cannot be represented in JSON"),
                )
            });
    }
    if let Ok(mapping) = value.cast::<PyMapping>() {
        let mut object = Map::new();
        for entry in mapping.items()?.try_iter()? {
            let entry = entry?;
            let key: Bound<'_, PyAny> = entry.get_item(0)?;
            let item: Bound<'_, PyAny> = entry.get_item(1)?;
            let key = key
                .cast::<PyString>()
                .map_err(|_| error(DrasiErrorCode::ConfigInvalid, "object keys must be strings"))?;
            object.insert(key.to_cow()?.into_owned(), py_to_json(&item)?);
        }
        return Ok(Value::Object(object));
    }
    // Strings and mappings are handled above, so any remaining sequence is a list.
    if let Ok(sequence) = value.cast::<PySequence>() {
        let mut items = Vec::new();
        for item in sequence.try_iter()? {
            items.push(py_to_json(&item?)?);
        }
        return Ok(Value::Array(items));
    }

    Err(error(
        DrasiErrorCode::ConfigInvalid,
        format!(
            "cannot convert {} to JSON",
            value.get_type().name()?.to_cow()?
        ),
    ))
}

/// Converts a `serde_json::Value` into the corresponding Python object.
pub fn json_to_py<'py>(py: Python<'py>, value: &Value) -> PyResult<Bound<'py, PyAny>> {
    Ok(match value {
        Value::Null => py.None().into_bound(py),
        Value::Bool(flag) => PyBool::new(py, *flag).to_owned().into_any(),
        Value::Number(number) => {
            if let Some(integer) = number.as_i64() {
                integer.into_pyobject(py)?.into_any()
            } else if let Some(unsigned) = number.as_u64() {
                unsigned.into_pyobject(py)?.into_any()
            } else {
                number
                    .as_f64()
                    .unwrap_or(f64::NAN)
                    .into_pyobject(py)?
                    .into_any()
            }
        }
        Value::String(text) => PyString::new(py, text).into_any(),
        Value::Array(items) => {
            let list = PyList::empty(py);
            for item in items {
                list.append(json_to_py(py, item)?)?;
            }
            list.into_any()
        }
        Value::Object(entries) => {
            let dict = PyDict::new(py);
            for (key, item) in entries {
                dict.set_item(key, json_to_py(py, item)?)?;
            }
            dict.into_any()
        }
    })
}

/// The operation requested by a change, after alias normalisation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ChangeOp {
    Insert,
    Update,
    Delete,
}

impl ChangeOp {
    /// Normalises an operation name. `add`/`insert` and `remove`/`delete` are
    /// synonyms, and matching is case-insensitive.
    pub fn parse(op: &str) -> PyResult<Self> {
        match op.trim().to_ascii_lowercase().as_str() {
            "insert" | "add" => Ok(Self::Insert),
            "update" => Ok(Self::Update),
            "delete" | "remove" => Ok(Self::Delete),
            other => Err(error(
                DrasiErrorCode::UnknownChangeOp,
                format!(
                    "unknown change op '{other}', expected one of: \
                     insert (add), update, delete (remove)"
                ),
            )),
        }
    }
}

fn lookup<'py>(change: &Bound<'py, PyDict>, keys: &[&str]) -> PyResult<Option<Bound<'py, PyAny>>> {
    for key in keys {
        if let Some(value) = change.get_item(key)? {
            if !value.is_none() {
                return Ok(Some(value));
            }
        }
    }
    Ok(None)
}

fn required_str(
    change: &Bound<'_, PyDict>,
    keys: &[&str],
    code: DrasiErrorCode,
    message: &str,
) -> PyResult<String> {
    let value = lookup(change, keys)?.ok_or_else(|| error(code, message))?;
    value
        .extract::<String>()
        .map_err(|_| error(code, format!("{message} (got a non-string value)")))
}

fn labels(change: &Bound<'_, PyDict>) -> PyResult<Arc<[Arc<str>]>> {
    let Some(value) = lookup(change, &["labels"])? else {
        return Ok(Arc::from(Vec::new()));
    };
    let names: Vec<String> = value.extract().map_err(|_| {
        error(
            DrasiErrorCode::ConfigInvalid,
            "'labels' must be a sequence of strings",
        )
    })?;
    Ok(names.into_iter().map(Arc::from).collect())
}

fn properties(change: &Bound<'_, PyDict>) -> PyResult<ElementPropertyMap> {
    let Some(value) = lookup(change, &["properties"])? else {
        return Ok(ElementPropertyMap::new());
    };
    let json = py_to_json(&value)?;
    if !json.is_object() {
        return Err(error(
            DrasiErrorCode::ConfigInvalid,
            "'properties' must be a mapping",
        ));
    }
    Ok(ElementPropertyMap::from(&json))
}

fn effective_from(change: &Bound<'_, PyDict>) -> PyResult<u64> {
    match lookup(change, EFFECTIVE_FROM_KEYS)? {
        Some(value) => value.extract::<u64>().map_err(|_| {
            error(
                DrasiErrorCode::ConfigInvalid,
                "'effective_from' must be a non-negative integer of milliseconds since the epoch",
            )
        }),
        None => Ok(0),
    }
}

/// Builds a [`SourceChange`] from a Python mapping.
///
/// A change describes a node, or a relation when both ends are supplied.
pub fn source_change_from_py(source_id: &str, change: &Bound<'_, PyAny>) -> PyResult<SourceChange> {
    let change = change.cast::<PyDict>().map_err(|_| {
        error(
            DrasiErrorCode::ChangeNotObject,
            "a change must be a mapping",
        )
    })?;

    let op = ChangeOp::parse(&required_str(
        change,
        &["op"],
        DrasiErrorCode::ChangeOpRequired,
        "a change requires an 'op'",
    )?)?;
    let element_id = required_str(
        change,
        &["id"],
        DrasiErrorCode::ChangeIdRequired,
        "a change requires an 'id'",
    )?;

    let metadata = ElementMetadata {
        reference: ElementReference::new(source_id, &element_id),
        labels: labels(change)?,
        effective_from: effective_from(change)?,
    };

    if op == ChangeOp::Delete {
        return Ok(SourceChange::Delete { metadata });
    }

    let start_id = lookup(change, START_ID_KEYS)?
        .map(|value| value.extract::<String>())
        .transpose()
        .map_err(|_| error(DrasiErrorCode::ConfigInvalid, "'start_id' must be a string"))?;
    let end_id = lookup(change, END_ID_KEYS)?
        .map(|value| value.extract::<String>())
        .transpose()
        .map_err(|_| error(DrasiErrorCode::ConfigInvalid, "'end_id' must be a string"))?;

    let element = match (start_id, end_id) {
        (Some(start), Some(end)) => Element::Relation {
            metadata,
            in_node: ElementReference::new(source_id, &start),
            out_node: ElementReference::new(source_id, &end),
            properties: properties(change)?,
        },
        (None, None) => Element::Node {
            metadata,
            properties: properties(change)?,
        },
        // One end without the other is always a mistake — silently treating it
        // as a node would drop the relation the caller asked for.
        _ => {
            return Err(error(
                DrasiErrorCode::RelationRequiresBothEnds,
                "a relation change requires both 'start_id' and 'end_id'",
            ))
        }
    };

    Ok(match op {
        ChangeOp::Insert => SourceChange::Insert { element },
        ChangeOp::Update => SourceChange::Update { element },
        ChangeOp::Delete => unreachable!("handled above"),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use pyo3::types::PyDictMethods;

    /// PyO3 needs a live interpreter before any Python object — including the
    /// exceptions our error helpers build — can be created.
    fn init() {
        Python::initialize();
    }

    fn json(source: &str) -> Value {
        serde_json::from_str(source).expect("test fixture is valid JSON")
    }

    fn change<'py>(py: Python<'py>, entries: &[(&str, Bound<'py, PyAny>)]) -> Bound<'py, PyAny> {
        let dict = PyDict::new(py);
        for (key, value) in entries {
            dict.set_item(key, value).unwrap();
        }
        dict.into_any()
    }

    #[test]
    fn parses_operation_aliases() {
        for name in ["insert", "add", "INSERT", " Add "] {
            assert_eq!(ChangeOp::parse(name).ok(), Some(ChangeOp::Insert));
        }
        for name in ["delete", "remove", "REMOVE"] {
            assert_eq!(ChangeOp::parse(name).ok(), Some(ChangeOp::Delete));
        }
        assert_eq!(ChangeOp::parse("update").ok(), Some(ChangeOp::Update));
    }

    #[test]
    fn rejects_an_unknown_operation() {
        init();
        assert!(ChangeOp::parse("upsert").is_err());
    }

    #[test]
    fn converts_scalars_to_json() {
        init();
        Python::attach(|py| {
            assert_eq!(py_to_json(&py.None().into_bound(py)).unwrap(), Value::Null);
            assert_eq!(
                py_to_json(&"hi".into_pyobject(py).unwrap()).unwrap(),
                json(r#""hi""#)
            );
            assert_eq!(
                py_to_json(&7i64.into_pyobject(py).unwrap()).unwrap(),
                json("7")
            );
            assert_eq!(
                py_to_json(&1.5f64.into_pyobject(py).unwrap()).unwrap(),
                json("1.5")
            );
        });
    }

    #[test]
    fn treats_bool_as_bool_not_int() {
        // Python's bool subclasses int, so checking int first would turn
        // `True` into `1` and silently change a query's semantics.
        init();
        Python::attach(|py| {
            let value = py_to_json(&true.into_pyobject(py).unwrap().to_owned().into_any()).unwrap();
            assert_eq!(value, Value::Bool(true));
        });
    }

    #[test]
    fn converts_containers_to_json() {
        init();
        Python::attach(|py| {
            let list = PyList::new(py, [1i64, 2, 3]).unwrap();
            assert_eq!(py_to_json(&list.into_any()).unwrap(), json("[1,2,3]"));

            let dict = PyDict::new(py);
            dict.set_item("a", 1i64).unwrap();
            dict.set_item("b", PyList::new(py, ["x"]).unwrap()).unwrap();
            assert_eq!(
                py_to_json(&dict.into_any()).unwrap(),
                json(r#"{"a":1,"b":["x"]}"#)
            );
        });
    }

    #[test]
    fn rejects_non_string_object_keys() {
        init();
        Python::attach(|py| {
            let dict = PyDict::new(py);
            dict.set_item(1i64, "value").unwrap();
            assert!(py_to_json(&dict.into_any()).is_err());
        });
    }

    #[test]
    fn rejects_values_with_no_json_representation() {
        init();
        Python::attach(|py| {
            assert!(py_to_json(&f64::NAN.into_pyobject(py).unwrap()).is_err());
            let module = py.import("sys").unwrap();
            assert!(py_to_json(&module.into_any()).is_err());
        });
    }

    #[test]
    fn json_round_trips_through_python() {
        init();
        Python::attach(|py| {
            let original = json(r#"{"s":"x","i":-4,"f":0.25,"b":false,"n":null,"l":[1,{"k":2}]}"#);
            let as_python = json_to_py(py, &original).unwrap();
            assert_eq!(py_to_json(&as_python).unwrap(), original);
        });
    }

    #[test]
    fn builds_a_node_insert() {
        init();
        Python::attach(|py| {
            let properties = PyDict::new(py);
            properties.set_item("total", 42i64).unwrap();
            let value = change(
                py,
                &[
                    ("op", "insert".into_pyobject(py).unwrap().into_any()),
                    ("id", "o1".into_pyobject(py).unwrap().into_any()),
                    ("labels", PyList::new(py, ["Order"]).unwrap().into_any()),
                    ("properties", properties.into_any()),
                ],
            );

            match source_change_from_py("orders", &value).unwrap() {
                SourceChange::Insert {
                    element: Element::Node { metadata, .. },
                } => {
                    assert_eq!(&*metadata.reference.source_id, "orders");
                    assert_eq!(&*metadata.reference.element_id, "o1");
                    assert_eq!(metadata.labels.len(), 1);
                    assert_eq!(&*metadata.labels[0], "Order");
                    assert_eq!(metadata.effective_from, 0);
                }
                other => panic!("expected a node insert, got {other:?}"),
            }
        });
    }

    #[test]
    fn a_delete_carries_only_metadata() {
        init();
        Python::attach(|py| {
            let value = change(
                py,
                &[
                    ("op", "remove".into_pyobject(py).unwrap().into_any()),
                    ("id", "o1".into_pyobject(py).unwrap().into_any()),
                ],
            );
            assert!(matches!(
                source_change_from_py("orders", &value).unwrap(),
                SourceChange::Delete { .. }
            ));
        });
    }

    #[test]
    fn relation_end_aliases_are_equivalent() {
        init();
        Python::attach(|py| {
            for (start_key, end_key) in [
                ("start_id", "end_id"),
                ("startId", "endId"),
                ("in_id", "out_id"),
                ("inId", "outId"),
            ] {
                let value = change(
                    py,
                    &[
                        ("op", "insert".into_pyobject(py).unwrap().into_any()),
                        ("id", "r1".into_pyobject(py).unwrap().into_any()),
                        (start_key, "c1".into_pyobject(py).unwrap().into_any()),
                        (end_key, "o1".into_pyobject(py).unwrap().into_any()),
                    ],
                );
                match source_change_from_py("graph", &value).unwrap() {
                    SourceChange::Insert {
                        element:
                            Element::Relation {
                                in_node, out_node, ..
                            },
                    } => {
                        assert_eq!(&*in_node.element_id, "c1", "{start_key}");
                        assert_eq!(&*out_node.element_id, "o1", "{end_key}");
                    }
                    other => panic!("expected a relation for {start_key}/{end_key}, got {other:?}"),
                }
            }
        });
    }

    #[test]
    fn one_sided_relations_are_rejected() {
        init();
        Python::attach(|py| {
            for key in ["start_id", "end_id"] {
                let value = change(
                    py,
                    &[
                        ("op", "insert".into_pyobject(py).unwrap().into_any()),
                        ("id", "r1".into_pyobject(py).unwrap().into_any()),
                        (key, "x".into_pyobject(py).unwrap().into_any()),
                    ],
                );
                assert!(source_change_from_py("graph", &value).is_err(), "{key}");
            }
        });
    }

    #[test]
    fn effective_from_accepts_both_spellings() {
        init();
        Python::attach(|py| {
            for key in ["effective_from", "effectiveFrom"] {
                let value = change(
                    py,
                    &[
                        ("op", "insert".into_pyobject(py).unwrap().into_any()),
                        ("id", "o1".into_pyobject(py).unwrap().into_any()),
                        (key, 1234i64.into_pyobject(py).unwrap().into_any()),
                    ],
                );
                match source_change_from_py("orders", &value).unwrap() {
                    SourceChange::Insert {
                        element: Element::Node { metadata, .. },
                    } => assert_eq!(metadata.effective_from, 1234, "{key}"),
                    other => panic!("expected a node, got {other:?}"),
                }
            }
        });
    }

    #[test]
    fn a_none_valued_key_falls_through_to_its_alias() {
        // Callers commonly pass every key with `None` defaults; an explicit
        // `None` must not shadow a populated alias.
        init();
        Python::attach(|py| {
            let value = change(
                py,
                &[
                    ("op", "insert".into_pyobject(py).unwrap().into_any()),
                    ("id", "r1".into_pyobject(py).unwrap().into_any()),
                    ("start_id", py.None().into_bound(py)),
                    ("startId", "c1".into_pyobject(py).unwrap().into_any()),
                    ("end_id", "o1".into_pyobject(py).unwrap().into_any()),
                ],
            );
            assert!(matches!(
                source_change_from_py("graph", &value).unwrap(),
                SourceChange::Insert {
                    element: Element::Relation { .. }
                }
            ));
        });
    }

    #[test]
    fn malformed_changes_are_rejected() {
        init();
        Python::attach(|py| {
            let not_a_mapping = PyList::empty(py).into_any();
            assert!(source_change_from_py("orders", &not_a_mapping).is_err());

            let no_op = change(py, &[("id", "o1".into_pyobject(py).unwrap().into_any())]);
            assert!(source_change_from_py("orders", &no_op).is_err());

            let no_id = change(
                py,
                &[("op", "insert".into_pyobject(py).unwrap().into_any())],
            );
            assert!(source_change_from_py("orders", &no_id).is_err());

            let bad_labels = change(
                py,
                &[
                    ("op", "insert".into_pyobject(py).unwrap().into_any()),
                    ("id", "o1".into_pyobject(py).unwrap().into_any()),
                    ("labels", 5i64.into_pyobject(py).unwrap().into_any()),
                ],
            );
            assert!(source_change_from_py("orders", &bad_labels).is_err());

            let bad_properties = change(
                py,
                &[
                    ("op", "insert".into_pyobject(py).unwrap().into_any()),
                    ("id", "o1".into_pyobject(py).unwrap().into_any()),
                    ("properties", PyList::empty(py).into_any()),
                ],
            );
            assert!(source_change_from_py("orders", &bad_properties).is_err());
        });
    }
}
