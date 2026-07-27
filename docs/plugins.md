# Plugins

Drasi's sources, reactions, bootstrap providers, identity providers and secret
stores are **plugins**: self-contained native libraries (`.so` / `.dylib` /
`.dll`) that this host loads at runtime, exactly as `drasi-server` does.

## Where plugins come from

Plugins are published as OCI artifacts to `ghcr.io/drasi-project`:

```
ghcr.io/drasi-project/{type}/{kind}:{version}-{arch}

ghcr.io/drasi-project/source/postgres:0.1.13-linux-amd64
ghcr.io/drasi-project/source/mock:0.2.7-darwin-arm64
ghcr.io/drasi-project/reaction/log:0.2.5-linux-arm64
```

Short references are expanded against the default registry, so `source/postgres`
means `ghcr.io/drasi-project/source/postgres`.

A companion package, `ghcr.io/drasi-project/drasi-plugin-directory`, is a
searchable index: each of its tags is a `{type}.{kind}` pair such as
`source.postgres` or `reaction.log`.

Each artifact is an OCI image manifest with two layers — the plugin binary
(`application/vnd.drasi.plugin.v1+binary`) and its metadata
(`application/vnd.drasi.plugin.v1+metadata`) — plus `io.drasi.plugin.*`
annotations describing what it is and what it was built against.

## Compatibility

Because a plugin is native code loaded into your process, it is only usable by a
host that matches it. There are **three** independent gates:

1. **Registry annotations.** Before downloading, the resolver compares the
   artifact's `io.drasi.plugin.sdk-version`, `core-version` and `lib-version`
   annotations against this host's versions. They must match on `major.minor`.
2. **FFI ABI version.** After loading, the host calls the plugin's
   `drasi_plugin_metadata()` and compares its reported SDK version against the
   host's `FFI_SDK_VERSION`. This identifies the layout of the `repr(C)` structs
   that cross the boundary, and is deliberately decoupled from crate versions.
3. **Target triple.** The plugin's target triple must match the host's exactly.
   A `linux-amd64` build cannot load into an `aarch64-apple-darwin` host.

Inspect what this host offers:

```python
>>> import drasi
>>> drasi.host_info()
{'target_triple': 'aarch64-apple-darwin',
 'ffi_sdk_version': '0.11.0',
 'sdk_version': '0.10.0',
 'core_version': '0.5.7',
 'lib_version': '0.8.9'}
```

### Architecture suffixes

Tags are published per platform rather than as multi-architecture indices:

| Target triple | Tag suffix |
| --- | --- |
| `x86_64-unknown-linux-gnu` | `linux-amd64` |
| `aarch64-unknown-linux-gnu` | `linux-arm64` |
| `x86_64-unknown-linux-musl` | `linux-musl-amd64` |
| `aarch64-unknown-linux-musl` | `linux-musl-arm64` |
| `x86_64-apple-darwin` | `darwin-amd64` |
| `aarch64-apple-darwin` | `darwin-arm64` |
| `x86_64-pc-windows-msvc` | `windows-msvc-amd64`, falling back to `windows-amd64` |

You do not normally need this table — `install_plugin()` resolves the right tag
for you.

## Why the crate pins are fixed

`Cargo.toml` pins `drasi-core`, `drasi-lib` and `drasi-plugin-sdk` to exact
versions. This is deliberate: those versions are what gate 1 compares against.
Bumping them without a matching plugin release would leave every published
plugin incompatible, and therefore uninstallable.

`scripts/check_registry_pins.py` (`make check-pins`) compares our pins against
the live registry and fails on drift. CI runs it too.

## Signing

Plugins are signed with cosign/Sigstore at publish time. Verification is
performed in-process — no `cosign` binary is required — and reports one of:

| Status | Meaning |
| --- | --- |
| `verified` | A trusted identity signed this exact artifact |
| `unsigned` | No signature was found, or verification was not requested |
| `tampered` | A signature exists but does not match the artifact |

Pass `require_signed=True` to reject anything that is not `verified`.

## Plugin configuration

The keys in a plugin's configuration are defined by the plugin, not by Drasi, so
they are passed through untouched. Drasi's own API is snake_case, but a plugin
that declares `intervalMs` wants exactly that.

Ask a loaded plugin what it accepts:

```python
schema = await drasi.source_config_schema("postgres")
print(schema["name"])  # source.postgres.PostgresSourceConfig
print(schema["schema"])  # OpenAPI definitions, including required fields
```

### A trap worth knowing about

Configuration mistakes are validated by the plugin, and a plugin that does not
recognise a key generally ignores it rather than failing. The Postgres source
has a particularly sharp example:

```python
{
    "tables": ["public.orders"],  # schema-qualified
    "tableKeys": [{"table": "orders", "keyColumns": ["id"]}],  # bare name
}
```

`tables` is schema-qualified but `tableKeys.table` is not. Qualify the latter and
the key is silently not applied: every update arrives as a second `ADD` rather
than an `UPDATE`, so rows accumulate, and deletes do nothing at all. Nothing
errors.

The same source also requires a Postgres publication to exist
(`CREATE PUBLICATION drasi_publication FOR TABLE ...`). Without it the source
connects, reports `Running`, and delivers nothing.
