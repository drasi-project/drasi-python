---
title: "Plugins"
linkTitle: "Plugins"
weight: 40
description: >
  Search, install, verify and load Drasi's native source, reaction and bootstrap plugins.
---

Drasi's sources, reactions, bootstrap providers, secret stores and identity providers
are **plugins**: self-contained native libraries (`.so`, `.dylib`, `.dll`) that this
host loads at runtime, exactly as `drasi-server` does. All five types can be loaded and
selected from Python. That means a Python application
can follow Postgres, Kafka or Kubernetes without anyone writing Python bindings for
each one.

## Installing one

```python
resolved = await drasi.install_plugin("source/postgres")
```

That resolves the reference, picks the build matching this host, downloads it, loads
it, and returns what it found. Short references are expanded against the default
registry, so `source/postgres` means `ghcr.io/drasi-project/source/postgres`.

Once loaded, the kind is available to `add_source`, `add_reaction` or the `bootstrap`
argument:

```python
await drasi.add_source("postgres", "db", {...})
```

## Finding one

```python
for hit in await drasi.search_plugins("postgres"):
    print(hit["reference"], [v["version"] for v in hit["versions"]])
```

Passing no query lists everything. `list_plugin_tags` shows the tags of a single
repository, and `resolve_plugin` reports what a reference would resolve to on this
host without downloading it.

The registry carries source, reaction, bootstrap, identity and secret-store plugins —
`postgres`, `mysql`, `mssql`, `kafka`, `kubernetes` and `neo4j` sources among them, and
`dashboard`, `http`, `grpc`, `sse` and `mcp` reactions. Rather than trust a list here
that goes stale as the registry grows, ask it:

```python
kinds = {}
for hit in await drasi.search_plugins():
    kinds.setdefault(hit["plugin_type"], []).append(hit["kind"])
```

## Where plugins come from

Plugins are published as OCI artifacts:

```text
ghcr.io/drasi-project/{type}/{kind}:{version}-{arch}

ghcr.io/drasi-project/source/postgres:0.2.7-linux-amd64
ghcr.io/drasi-project/reaction/dashboard:0.1.3-darwin-arm64
```

Note the per-architecture tags: these are not multi-arch image indexes, so the
architecture is part of the tag.

## Compatibility

A plugin is native code loaded into your process, so it is only usable by a host that
matches it. There are **three** independent gates:

1. **Registry annotations** — before downloading, the resolver compares the artifact's
   `sdk-version`, `core-version` and `lib-version` annotations against this host's.
   They must match on `major.minor`.
2. **FFI ABI version** — after loading, the host compares the plugin's reported SDK
   version against its own `FFI_SDK_VERSION`, which describes the layout of the structs
   crossing the boundary and is deliberately decoupled from crate versions.
3. **Target triple** — must match exactly. A `linux-amd64` build cannot load into an
   `aarch64-apple-darwin` host.

Inspect what this host offers:

```python
>>> import drasi
>>> drasi.host_info()
{'arch_suffix': 'darwin-arm64',
 'core_version': '0.5.7',
 'ffi_sdk_version': '0.11.0',
 'index_backends': ['memory', 'rocksdb'],
 'lib_version': '0.8.9',
 'sdk_version': '0.10.0',
 'target_triple': 'aarch64-apple-darwin'}
```

An incompatible plugin raises `PluginCompatibilityError` at resolve time rather than
crashing later, and a reference with no build for this platform raises
`PluginNotFoundError`.

## Signature verification

Plugins can be verified with [cosign](https://docs.sigstore.dev/) keyless signatures:

```python
await drasi.install_plugin(
    "source/postgres",
    verify=True,
    require_signed=True,
    trusted_identities=[
        ("https://github.com/drasi-project/.*", "https://token.actions.githubusercontent.com")
    ],
)
```

`verify=True` checks a signature when one is present. `require_signed=True` additionally
refuses to install an unsigned plugin.

Verification failure raises `PluginSignatureError`.

## Pinning with a lockfile

Resolving a floating reference gives you whatever is newest, which is not what you want
in a deployment. Write a lockfile once:

```python
await drasi.install_plugin("source/postgres")
await drasi.write_lockfile("plugins")
```

and install exactly those digests everywhere else:

```python
await drasi.install_from_lockfile("plugins")
```

`Drasi.read_lockfile(directory)` returns the entries, each with the reference, resolved
digest and file hash.

## Loading from disk

Plugins already on disk load without touching a registry, which is the usual choice in
an air-gapped or container-built environment:

```python
summary = await drasi.load_plugins("/opt/drasi/plugins")
print(summary["sources"], summary["reactions"], summary["bootstrap"])
```

`watch_plugins(directory)` keeps watching, picking up plugins added later.

A file is treated as a plugin if its name begins with `drasi_` or `libdrasi_`
and it exports the plugin entry point; the name is a filter, the entry point is
the decision. Shared libraries in the directory that were not loaded are
reported as `skipped`, so a plugin that is present but unrecognised shows up as
a number rather than as nothing at all.

## Plugin configuration

Configuration keys belong to the plugin, not to this library, so they are passed
through untouched. Ask a loaded plugin what it accepts:

```python
schema = await drasi.source_config_schema("postgres")
```

There are `reaction_config_schema` and `bootstrap_config_schema` equivalents. What those
keys mean, and which combinations are valid, is the plugin's business — consult the
plugin's own documentation rather than expecting this library to describe it.

## Secrets

Rather than putting credentials in a config dict, a plugin can ask the host to resolve
a reference:

```python
drasi = await Drasi.create("app", secrets={"PGPASSWORD": os.environ["PGPASSWORD"]})

await drasi.add_source(
    "postgres",
    "db",
    {
        "host": "localhost",
        "port": 5432,
        "user": "postgres",
        "database": "app",
        "password": {"kind": "Secret", "name": "PGPASSWORD"},
        "tables": ["public.orders"],
        "tableKeys": [{"table": "orders", "keyColumns": ["id"]}],
    },
)
```

The plugin never sees the value until it asks for it, and the config you log or store
holds only the reference. `{"kind": "EnvironmentVariable", "name": "PGPASSWORD"}` works
the same way, and takes an optional `default`.

### Resolving from a secret store

Passing every secret to `create` means having them all to hand. A `secret-store` plugin
resolves them on demand instead:

```python
await drasi.install_plugin("secret-store/file")
await drasi.use_secret_store("file", {"path": "/etc/myapp/secrets.json"})
```

From then on a reference a plugin cannot find in the mapping given to `create` is
looked up in the store. `azure-keyvault` and `keyring` are published alongside `file`;
ask each what it needs with `secret_store_config_schema(kind)`.

A resolved value is cached, because the lookup crosses into the store's own runtime and
a plugin that re-reads its configuration on every reconnect would otherwise pay for it
each time.

### Identity providers

`password` and `token` are built into the engine. Any other `identity` kind names an
`identity/*` plugin:

```python
drasi = await Drasi.create(
    "app",
    identity={"kind": "azure", "client_id": "..."},
    plugins_dir="/opt/drasi/plugins",
)
```

`plugins_dir` is required here, and only here. An identity provider reaches the engine
through its builder, which runs before anything could call `install_plugin`, so the
plugin has to be on disk when `create` is called. Download it ahead of time with
`install_plugin(..., load=False, directory=...)`, or ship it in your image.

Whether the credentials are then *used* is up to the component: a source or reaction
asks its identity provider only if it authenticates that way. Of the published sources,
`dataverse` does; `postgres` and the rest take their credentials from their own
configuration, so giving one an identity provider changes nothing.

## Next

- [Concepts: bootstrap](../../concepts/#bootstrap) — loading what already exists.
- [Postgres dashboard example](../../examples/postgres-dashboard/) — plugins end to end.
