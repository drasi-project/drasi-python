---
title: "Examples"
linkTitle: "Examples"
weight: 50
description: >
  Runnable programs, from a first query to a live dashboard over Postgres.
---

The [`examples/`](https://github.com/drasi-project/drasi-python/tree/main/examples)
directory in the repository holds runnable programs, each focused on one thing. They
run against a local build of the repository, so they exercise your changes rather than
the released package — see the
[README](https://github.com/drasi-project/drasi-python/blob/main/examples/README.md)
there for the two commands that set that up.

| Example | Shows |
| --- | --- |
| `python_source.py` | Pushing changes into a Python source and printing the diffs |
| `streaming.py` | Consuming results as an async iterator |
| `sync_quickstart.py` | The same thing with the blocking API |
| `install_plugin.py` | Installing a plugin from `ghcr.io` and using it |
| `postgres_cdc.py` | Following a real Postgres table through change data capture |

Only the last two need network access, and `postgres_cdc.py` needs Docker.

## Longer walkthroughs

<div class="card-grid card-grid--2">
  <a href="postgres-dashboard/">
    <div class="unified-card unified-card--howto">
      <div class="unified-card-icon"><i class="fas fa-chart-line"></i></div>
      <div class="unified-card-content">
        <h3 class="unified-card-title">Postgres dashboard</h3>
        <p class="unified-card-summary">Follow a Postgres table into a live dashboard, using only published plugins.</p>
      </div>
    </div>
  </a>
</div>
