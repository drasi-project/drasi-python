# Documentation site

The [drasi-lib for Python](https://drasi-project.github.io/drasi-python/) docs, built
with [Hugo](https://gohugo.io) and the [Docsy](https://www.docsy.dev) theme. This
mirrors the setup used by `drasi-project/docs` and `drasi-project/drasi-nodejs`.

`.github/workflows/website.yml` builds and deploys it to GitHub Pages on every push to
`main` that touches this directory. Pull requests build it without deploying.

## Running it locally

Docsy is a git submodule, so fetch it first if you cloned without `--recursive`:

```bash
git submodule update --init --recursive
```

You need [Hugo **extended**](https://gohugo.io/installation/) 0.110 or newer — the
standard build cannot compile the theme's SCSS — and Node for the theme's assets:

```bash
cd website
npm install
npm --prefix themes/docsy install
npm run serve      # http://localhost:1313/drasi-python/
```

To reproduce what CI publishes:

```bash
npm run build
```

## Layout

```text
content/
  _index.md                 landing page
  docs/
    _index.md               documentation home
    getting-started/        install and first query
    concepts/               the change-driven model
    guides/                 task-focused walkthroughs
    api/                    generated API reference
    examples/               runnable programs and walkthroughs
assets/scss/                project style overrides
layouts/                    template overrides
themes/docsy/               the theme, as a git submodule
```

## The API reference is generated

`content/docs/api/_index.md` is produced from `python/drasi/_drasi.pyi` — the same
stubs your type checker reads — so it cannot claim methods the package does not have:

```bash
python scripts/generate_api_reference.py           # rewrite it
python scripts/generate_api_reference.py --check   # fail if it is stale
```

`tests/unit/test_docs.py` runs that check, and also verifies that the documented error
codes match `drasi.ERROR_CODES` and that no page links to one that does not exist.
Edit the stub, not the page.

## Upgrading Docsy

The submodule is pinned to a commit rather than tracking `main`, because Docsy has
restructured where it keeps layouts and a moving pin breaks the build without warning.
To move it, check out the new commit inside `themes/docsy`, rebuild locally, and commit
the updated gitlink.
