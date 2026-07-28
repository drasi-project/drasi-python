# Releasing

This package is the `drasi-lib` PyPI distribution and is imported as `drasi`.
It is not yet released to PyPI.

## Versioning policy

Use Semantic Versioning. While the project is `0.y.z`, minor versions may make
breaking API changes, but they should still be called out clearly in the
changelog. Patch versions are for compatible fixes.

The package version has one source of truth:

- `Cargo.toml` `[package].version`

`pyproject.toml` uses `dynamic = ["version"]`, so maturin reads that Cargo
version when it builds wheels and the sdist. The extension exposes the same
value as `drasi.__version__` through `env!("CARGO_PKG_VERSION")`.

To bump the package version:

1. Edit `Cargo.toml`.
2. Run `cargo check` or another Cargo command that refreshes `Cargo.lock`.
3. Move the relevant changelog entries from `Unreleased` to the new version.
4. Run `scripts/check_version_sync.py`.

Do not add a literal package version to Python, docs or workflow files unless
`scripts/check_version_sync.py` can verify it.

## Drasi crate pins are not routine dependency bumps

`drasi-core`, `drasi-lib` and `drasi-plugin-sdk` are pinned exactly in
`Cargo.toml`. Published plugins in `ghcr.io/drasi-project` record the versions
they were built against, and this host rejects any plugin whose `major.minor`
does not match. Bumping those pins requires a registry-aware plugin release
plan, not just a dependency update.

Before changing those pins, read `docs/plugins.md` and run:

```bash
.venv/bin/python scripts/check_registry_pins.py
```

## One-time PyPI trusted publishing setup

A PyPI project owner must configure trusted publishing before the first tag is
pushed:

1. Create the `drasi-lib` project on PyPI, if it does not exist yet.
2. Add a trusted publisher for `drasi-project/drasi-python`.
3. Point it at the release workflow file, `release.yml`.
4. Set the environment name if the workflow uses one. Keep the PyPI setting and
   workflow in sync.

No PyPI API token should be stored in GitHub. The release workflow is expected
to publish with OIDC trusted publishing.

## Cutting a release

1. Ensure `main` is green and the changelog has a section for the release.
2. Verify locally:

   ```bash
   .venv/bin/python scripts/check_version_sync.py
   .venv/bin/python scripts/check_registry_pins.py
   .venv/bin/ruff check .
   .venv/bin/ruff format --check .
   .venv/bin/pytest
   ```

3. Create and push a signed tag matching the package version:

   ```bash
   git tag -s v0.1.0 -m "v0.1.0"
   git push origin v0.1.0
   ```

4. The release workflow should build abi3 wheels for the supported Linux,
   macOS and Windows targets, build an sdist, and publish them to PyPI through
   trusted publishing. Do not rely on particular job names; check the workflow
   run attached to the tag.

## Verifying a release

After PyPI publishing completes:

```bash
python -m venv .release-check
.release-check/bin/python -m pip install --upgrade pip
.release-check/bin/python -m pip install drasi-lib==0.1.0
.release-check/bin/python - <<'PY'
import drasi

assert drasi.__version__ == "0.1.0"
print(drasi.host_info())
PY
rm -rf .release-check
```

Also check that the GitHub release, PyPI file list and changelog all refer to
the same version, and that at least one clean environment can import `drasi`.

## Yanking or fixing a bad release

PyPI files are immutable. If a release is bad:

1. Yank the bad version on PyPI with a reason. This stops normal installs from
   selecting it while preserving reproducibility for pinned users.
2. Leave the Git tag in place unless maintainers agree it was never published
   successfully. Do not move a published tag.
3. Fix forward with the next patch version, or the next minor version if the
   fix is breaking under the pre-1.0 policy.
4. Record the yanked version and replacement in the changelog.
