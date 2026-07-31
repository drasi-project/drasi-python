# Tutorials

Hands-on, end-to-end walkthroughs built on [`drasi-lib`](https://pypi.org/project/drasi-lib/),
the Python binding for Drasi's continuous-query engine. Each tutorial is a
self-contained project you can clone and run.

| Tutorial | What you learn | How to run it |
| --- | --- | --- |
| [getting-started](getting-started) | The change-driven basics — PostgreSQL CDC and three continuous queries (a filter, a `count` aggregation, and a temporal `inactive-people`), printed live by a **Python reaction** in a no-UI console app you drive with SQL | Open the **Getting Started Tutorial (Python)** dev container (or a Codespace) and follow [tutorials/getting-started](getting-started) |
| [building-comfort](building-comfort) | Smart-building comfort monitoring — PostgreSQL CDC, six continuous queries with synthetic joins and aggregation, and a **Python reaction that drives a Streamlit UI** (with simulation, reset and per-room controls) | Open the **Building Comfort Tutorial (Python)** dev container (or a Codespace) and follow [tutorials/building-comfort](building-comfort) |
| [curbside-pickup](curbside-pickup) | Cross-database joins — a PostgreSQL `orders` store and a MySQL `vehicles` store joined by license plate, six continuous queries (incl. a temporal `drasi.trueFor` delay), rendered and driven from **one integrated Streamlit UI** powered by a Python reaction | Open the **Curbside Pickup Tutorial (Python)** dev container (or a Codespace) and follow [tutorials/curbside-pickup](curbside-pickup) |

## How these tutorials are authored

Each tutorial is written once in `tutorials/<name>/_index.md` (the single source
of truth), which is mounted into the [documentation site](../website) so it also
renders at <https://drasi-project.github.io/drasi-python/docs/tutorials/>. The
GitHub-friendly `tutorials/<name>/README.md` is generated from that same file:

```bash
python3 scripts/render-tutorials.py          # regenerate the READMEs
python3 scripts/render-tutorials.py --check   # fail if any are stale (run in CI)
```

Edit the `_index.md`, not the `README.md`.
