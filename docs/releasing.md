# Releasing

This package is the `drasi-lib` PyPI distribution and is imported as `drasi`.

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

This is already done for `drasi-lib`; it is kept for reference, and for anyone
setting up a sibling package. How you create a project decides **who owns
it**, and that is easy to get wrong.

The "pending publisher" form lives under your *account* sidebar
(<https://pypi.org/manage/account/publishing/>), so a project created that way
is owned by **your personal account**, not by an organization — even if you are
an owner of one. Prefer the organization route below.

### Preferred: create the project in the organization first

1. **Your organizations** → **Manage** on the Drasi organization → **Projects**.
2. At the bottom of the page, enter `drasi-lib` and click **Create**. This
   reserves the name under the organization.
3. Open the new project → **Publishing** → add a Trusted Publisher (a normal
   one, not a pending one, because the project now exists) with:

   | Field | Value |
   | --- | --- |
   | Owner | `drasi-project` |
   | Repository name | `drasi-python` |
   | Workflow name | `release.yml` |
   | Environment name | *leave blank* |

The project is organization-owned from the outset, and no transfer is needed.

### Fallback: pending publisher, then transfer

> Only useful for a project that does not exist yet. Once the name is
> registered, a pending publisher for it can no longer be created, and the
> project-level route above is the only option.

If the project has already been created from a personal account, an
organization **Owner** can move it: **Your organizations** → **Manage** →
**Projects** → select the project at the bottom → **Transfer existing project**.
Ownership shifts from the individual to the organization. This only works for
projects already associated with that user's account.

If you go this route, register the pending publisher at
<https://pypi.org/manage/account/publishing/> with the same four values above
plus **PyPI Project Name** `drasi-lib`.

### Organization roles do not grant project permissions

An organization **Manager** can create a project but cannot manage it
afterwards, because managing a specific project
needs a **project role** — held as a collaborator — and an organization role
does not confer one. The symptom is a greyed-out **Manage** button and a `403`
on the project's settings URL, immediately after successfully creating it.

Only an organization **Owner** can add project collaborators. Ask one to do
either of these:

- **Grant access**: **Your organizations** → **Manage** (Drasi) → **Projects**
  → **Manage** on `drasi-lib` → **Collaborators** → add the maintainer with the
  **Owner** role. They can then configure the trusted publisher themselves.
- **Or just do it**: the Owner configures the trusted publisher directly, using
  the values above. Nothing further is needed from anyone else.

Deleting a project is also Owner-only, so a Manager cannot undo a mistaken
creation either.

This is a PyPI-side limitation rather than a misconfiguration on our side,
reported upstream as
[pypi/warehouse#20337](https://github.com/pypi/warehouse/issues/20337).

### If the organization's "Manage" button is greyed out

The organization's **Projects** list is not the route to a project's settings.
Use **Your projects** (<https://pypi.org/manage/projects/>) instead, which is
where PyPI's own documentation sends you, or go straight to
<https://pypi.org/manage/project/drasi-lib/settings/publishing/>.

If that is refused rather than merely hidden, it is a permissions problem
rather than a navigation one. Managing a specific project needs a **project
role**, which an organization role does not confer on its own: an organization
Owner has to add you as a collaborator on the project with the **Owner** role
(**Manage** the organization → **Projects** → the project → **Collaborators**).

For a Company organization, also check the subscription is current — project
management is restricted while billing is lapsed.

### Either way

The environment field must be blank, because the `publish` job in
`.github/workflows/release.yml` declares no `environment:`. If you add one on
either side, add it to both — a mismatch fails the OIDC exchange with a
confusing "not a trusted publisher" error rather than a helpful one.

Nothing else is needed: no PyPI API token, and no GitHub secret. The workflow
publishes with OIDC, which is why its `publish` job requests
`permissions: id-token: write`.

A pending publisher does **not** reserve the name until the first successful
publish. Creating the project in the organization first does reserve it, which
is the other reason to prefer that route.

To rehearse without touching the real index, repeat the setup on
<https://test.pypi.org/> and point the publish step at TestPyPI with
`repository-url`.

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
   git tag -s v0.2.0 -m "v0.2.0"
   git push origin v0.2.0
   ```

4. The release workflow should build abi3 wheels for the supported Linux,
   macOS and Windows targets, build an sdist, and publish them to PyPI through
   trusted publishing. Do not rely on particular job names; check the workflow
   run attached to the tag.

## Verifying a release

After PyPI publishing completes. The interpreter must be 3.10 or newer — the
wheels are abi3 with `requires-python >=3.10`, and a system `python3` that is
older resolves nothing at all, with an error that mentions only the Python
version:

```bash
uv venv --python 3.12 .release-check
uv pip install --python .release-check/bin/python drasi-lib==0.2.0
.release-check/bin/python - <<'PY'
import drasi

assert drasi.__version__ == "0.2.0", drasi.__version__
assert ".release-check" in drasi.__file__, f"import leaked from {drasi.__file__}"
print(drasi.host_info())
PY
rm -rf .release-check
```

The second assertion matters: run this from the repository root and the source
tree can satisfy the import instead of the wheel, so the check passes without
having tested the release at all.

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
