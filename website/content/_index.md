---
type: "docs"
title: "drasi-lib"
linkTitle: "drasi-lib"
no_list: true
hide_readingtime: true
description: "Embed the Drasi continuous-query engine in your Python application"
cascade:
  - type: "docs"
---

<div class="hero-section hero-section--compact">
  <h1 class="hero-title">Embed Drasi in your Python app</h1>
  <p class="hero-subtitle"><code>drasi-lib</code> runs Drasi's continuous-query engine <strong>in-process</strong> in Python — no servers, no brokers, no Kubernetes. Define sources and reactions in plain Python, or load native Drasi plugins at runtime.</p>

  <div class="cta-group">
    <a href="docs/getting-started/" class="cta-button cta-button--primary">
      <i class="fas fa-rocket"></i>
      Get Started
    </a>
    <a href="docs/concepts/" class="cta-button cta-button--secondary">
      <i class="fas fa-lightbulb"></i>
      Why Drasi?
    </a>
  </div>
</div>

## How drasi-lib Works

<p class="section-intro">Install the package, create sources, continuous queries and reactions in code, and handle changes as they happen. Everything runs in-process — a native (<a href="https://pyo3.rs">PyO3</a>) extension hosts the embeddable Drasi engine inside Python, with prebuilt abi3 wheels for Linux, macOS and Windows.</p>

<div class="flow-diagram">
  <div class="flow-step">
    <div class="flow-step__icon">
      <i class="fab fa-python"></i>
    </div>
    <div class="flow-step__label">Install</div>
    <div class="flow-step__description">pip install drasi-lib</div>
  </div>

  <div class="flow-arrow">
    <i class="fas fa-arrow-right"></i>
  </div>

  <div class="flow-step">
    <div class="flow-step__icon">
      <i class="fas fa-code"></i>
    </div>
    <div class="flow-step__label">Write Code</div>
    <div class="flow-step__description">Create sources, queries and reactions</div>
  </div>

  <div class="flow-arrow">
    <i class="fas fa-arrow-right"></i>
  </div>

  <div class="flow-step">
    <div class="flow-step__icon">
      <i class="fas fa-bolt"></i>
    </div>
    <div class="flow-step__label">React to Change</div>
    <div class="flow-step__description">Handle result diffs in your app</div>
  </div>
</div>

Push graph changes from your own code into a Python **source**, run a **continuous
query** in Cypher or GQL, and receive the *added*, *updated* and *removed* rows in a
Python **reaction** — without leaving your process. When you need to connect to real
systems, load Drasi's native source, reaction and bootstrap plugins at runtime, or
pull them straight from the `ghcr.io/drasi-project` OCI registry.

## When to Use drasi-lib

`drasi-lib` suits a Python application or service that needs **precise change
detection** without deploying separate infrastructure:

- **Event-driven services** — react to data changes without polling, with the before
  and after state of every change.
- **Real-time dashboards** — stream live query results into a UI over your own
  channel, or load the `dashboard` reaction plugin and get one for free.
- **In-app reactive logic** — replace hand-wired event handling with declarative
  continuous queries over your application state.
- **Data and ML pipelines** — add reactive queries to an ETL step, a feature store,
  or a notebook, using the blocking API where `async` would be awkward.
- **Change data capture** — follow a Postgres, MySQL, SQL Server or Kafka source
  through a plugin, and query across several of them at once.

## Documentation

<p class="section-intro">Everything you need to build with <code>drasi-lib</code>, from a first continuous query to the full API surface.</p>

<div class="card-grid card-grid--2">
  <a href="docs/getting-started/">
    <div class="unified-card unified-card--tutorials">
      <div class="unified-card-icon"><i class="fas fa-rocket"></i></div>
      <div class="unified-card-content">
        <h3 class="unified-card-title">Getting Started</h3>
        <p class="unified-card-summary">Install the package and run your first continuous query in a couple of minutes.</p>
      </div>
    </div>
  </a>
  <a href="docs/concepts/">
    <div class="unified-card unified-card--concepts">
      <div class="unified-card-icon"><i class="fas fa-lightbulb"></i></div>
      <div class="unified-card-content">
        <h3 class="unified-card-title">Concepts</h3>
        <p class="unified-card-summary">The change-driven model: sources, continuous queries, reactions and bootstrap.</p>
      </div>
    </div>
  </a>
  <a href="docs/api/">
    <div class="unified-card unified-card--reference">
      <div class="unified-card-icon"><i class="fas fa-book"></i></div>
      <div class="unified-card-content">
        <h3 class="unified-card-title">API Reference</h3>
        <p class="unified-card-summary">Every method on the <code>Drasi</code> class, grouped by area, with types.</p>
      </div>
    </div>
  </a>
  <a href="docs/examples/postgres-dashboard/">
    <div class="unified-card unified-card--howto">
      <div class="unified-card-icon"><i class="fas fa-chart-line"></i></div>
      <div class="unified-card-content">
        <h3 class="unified-card-title">Postgres Dashboard</h3>
        <p class="unified-card-summary">An end-to-end example following a Postgres table into a live dashboard.</p>
      </div>
    </div>
  </a>
</div>
