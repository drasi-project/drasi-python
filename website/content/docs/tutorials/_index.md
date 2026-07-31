---
title: "Tutorials"
linkTitle: "Tutorials"
weight: 45
description: >
  End-to-end, hands-on walkthroughs you can run and drive yourself.
---

Longer, hands-on tutorials that build a complete demo with `drasi-lib` — a real
data source, continuous queries, and a reaction you can watch react in real time.

Each tutorial is authored once under
[`tutorials/`](https://github.com/drasi-project/drasi-python/tree/main/tutorials)
in the repository (runnable code plus its write-up), so you can read it here or
clone it and run it locally.

<div class="card-grid card-grid--2">
  <a href="building-comfort/">
    <div class="unified-card unified-card--tutorials">
      <div class="unified-card-icon"><i class="fas fa-building"></i></div>
      <div class="unified-card-content">
        <h3 class="unified-card-title">Building Comfort</h3>
        <p class="unified-card-summary">Monitor a smart building in real time with PostgreSQL CDC, six continuous queries with synthetic joins, and a Python reaction that drives a Streamlit UI.</p>
      </div>
    </div>
  </a>
  <a href="curbside-pickup/">
    <div class="unified-card unified-card--tutorials">
      <div class="unified-card-icon"><i class="fas fa-car"></i></div>
      <div class="unified-card-content">
        <h3 class="unified-card-title">Curbside Pickup</h3>
        <p class="unified-card-summary">Join a PostgreSQL orders store and a MySQL vehicles store by license plate — including a temporal delay query — in one integrated Streamlit UI driven by a Python reaction.</p>
      </div>
    </div>
  </a>
</div>
