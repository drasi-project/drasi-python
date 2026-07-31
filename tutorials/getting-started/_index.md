---
type: "docs"
title: "Getting Started"
linkTitle: "Getting Started"
weight: 10
description: >
  Connect Drasi to a live PostgreSQL database and build three continuous queries, step by step, in a small Python console app.
---

Imagine you want to react the instant data changes — a new row in a database, a value crossing a threshold, or something that *should* have changed but didn't. Drasi lets you express these as **continuous queries** that stay constantly up to date, with no polling.

This is the getting-started tutorial for **`drasi-lib`**, the Python binding that embeds Drasi's engine directly in your app. You'll connect Drasi to a live PostgreSQL table of messages — imagine a simple live message feed — and build three continuous queries that **filter** changes, **aggregate** them, and detect the **absence** of change. A single **Python reaction** prints each query's changes to the console, so there's no UI to build: you run one small console app, drive changes with plain SQL, and watch the queries react in your terminal.

<div class="flow-diagram">
  <div class="flow-step">
    <div class="flow-step__icon">
      <i class="fas fa-database"></i>
    </div>
    <div class="flow-step__label">Sources</div>
    <div class="flow-step__description">Connect to your data sources</div>
  </div>

  <div class="flow-arrow">
    <i class="fas fa-arrow-right"></i>
  </div>

  <div class="flow-step">
    <div class="flow-step__icon">
      <i class="fas fa-filter"></i>
    </div>
    <div class="flow-step__label">Continuous Queries</div>
    <div class="flow-step__description">Define what changes matter</div>
  </div>

  <div class="flow-arrow">
    <i class="fas fa-arrow-right"></i>
  </div>

  <div class="flow-step">
    <div class="flow-step__icon">
      <i class="fas fa-bolt"></i>
    </div>
    <div class="flow-step__label">Reactions</div>
    <div class="flow-step__description">Take action automatically</div>
  </div>
</div>

| Step | What You'll Do |
| ---- | ------------- |
| **[Step 1: Set Up Your Environment](#setup)** | Open the dev container (or install Python + Docker locally) |
| **[Step 2: Run the Demo](#run)** | One command starts PostgreSQL and the console app |
| **[Step 3: Read the Console](#console)** | See the three queries' initial results |
| **[Step 4: Drive Change](#drive)** | Add and delete messages with SQL, and watch the queries react |
| **[How It Works](#how)** | Understand the source, the three queries, and the Python reaction |

{{% alert title="Before you begin" color="info" %}}
- **Two terminals:** **Terminal 1** runs the console app (it stays in the foreground and prints changes). Use **Terminal 2** for the helper scripts that add and delete messages.
- **Working directory:** run every command from the tutorial directory (`tutorials/getting-started/`). The dev container opens there automatically; if you're running locally, `cd tutorials/getting-started` first.
- **Command tabs:** commands are shown in tabs (*bash / zsh* and *PowerShell*). Use the one for your shell.
- **Ports:** PostgreSQL is published on `5752`. There is no web UI.
{{% /alert %}}

## Step 1 of 4: Set Up Your Environment {#setup}

This tutorial needs **Python 3.10+** and **Docker** (for PostgreSQL). The easiest way to get everything is the **dev container**.

### Option A: Dev Container or GitHub Codespaces (recommended)

1. Open the [`drasi-python`](https://github.com/drasi-project/drasi-python) repository in VS Code and run **Reopen in Container** (or create a **Codespace** from the repo's **Code** menu).
2. When prompted for a configuration, choose **Getting Started Tutorial (Python)**.
3. Wait for the container to finish. Its setup script installs the tutorial's Python dependency (`drasi-lib`) and the Docker tooling for PostgreSQL.

That's it. Skip ahead to [Step 2](#run).

### Option B: Run Locally

You'll need **Python 3.10+**, **Docker**, and **bash** for the helper scripts. From the repository root, move into the tutorial directory and install the dependency:

{{< tabpane persist="header" >}}
{{< tab header="bash / zsh" lang="bash" >}}
cd tutorials/getting-started
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
{{< /tab >}}
{{< tab header="PowerShell" lang="powershell" >}}
cd tutorials/getting-started
python -m venv .venv; .venv\Scripts\Activate.ps1
pip install -r requirements.txt
{{< /tab >}}
{{< /tabpane >}}

`drasi-lib` ships as a prebuilt wheel, so no Rust toolchain is needed. It downloads the Postgres plugins it needs from `ghcr.io/drasi-project` the first time the app runs.

## Step 2 of 4: Run the Demo {#run}

In **Terminal 1**, start the demo:

{{< tabpane persist="header" >}}
{{< tab header="bash / zsh" lang="bash" >}}
bash scripts/start-demo.sh
{{< /tab >}}
{{< tab header="PowerShell" lang="powershell" >}}
powershell -ExecutionPolicy Bypass -File scripts/start-demo.ps1
{{< /tab >}}
{{< /tabpane >}}

The `start-demo` script starts PostgreSQL (seeding three messages, one of them exactly `Hello World`) and then runs the console app, which embeds the Drasi engine. On first start it downloads the plugins it needs (`source/postgres`, `bootstrap/postgres`) from `ghcr.io/drasi-project`, connects to the database, bootstraps the existing rows, and starts the three queries and the reaction.

Leave this running. Everything else happens in **Terminal 2**.

{{% alert title="Stopping and resetting" color="info" %}}
Press **Ctrl+C** in Terminal 1 to stop the app. To remove the database container when you're completely done, run `bash scripts/cleanup.sh` (bash) or `powershell -ExecutionPolicy Bypass -File scripts/cleanup.ps1` (PowerShell). Add `--volumes` (bash) or `-RemoveVolumes` (PowerShell) to also delete the data.
{{% /alert %}}

## Step 3 of 4: Read the Console {#console}

Once it's ready, the app prints each query's initial results and then waits for changes:

```text
=== Initial results ===

[hello-world-from] 1 row(s):
  MessageFrom='Brian Kernighan'  MessageId=2

[message-count] 3 row(s):
  Frequency=1  Message='Hello World'
  Frequency=1  Message='To infinity and beyond!'
  Frequency=1  Message='The Analytical Engine weaves algebraic patterns.'

[inactive-people] 0 row(s):

=== Watching for changes (Ctrl+C to stop) ===
```

`hello-world-from` already found the seeded `Hello World`; `message-count` shows each message once; `inactive-people` is empty. Because the seed messages then sit untouched, after about 20 seconds each sender crosses the inactivity threshold and the temporal query fires on its own:

```text
[13:06:09] [inactive-people] + LastMessageTimestamp='...T20:05:49+00:00'  MessageFrom='Buzz Lightyear'
[13:06:09] [inactive-people] + LastMessageTimestamp='...T20:05:49+00:00'  MessageFrom='Ada Lovelace'
[13:06:09] [inactive-people] + LastMessageTimestamp='...T20:05:49+00:00'  MessageFrom='Brian Kernighan'
```

## Step 4 of 4: Drive Change {#drive}

With Terminal 1 running the app, use **Terminal 2** to change the data and watch it react.

{{% alert title="No middle tier — the scripts just write to the database" color="info" %}}
The helper scripts run a plain SQL `INSERT` or `DELETE` against PostgreSQL — exactly what an existing app would already do. There's no API to call and no event to publish. Drasi observes the row change through logical replication (CDC), re-evaluates the affected queries, and calls the Python reaction, which prints the change. The **PowerShell** tabs make this obvious — they're the raw SQL statements.
{{% /alert %}}

### Add a message

Send a new `Hello World`, from someone new:

{{< tabpane persist="header" >}}
{{< tab header="bash / zsh" lang="bash" >}}
bash scripts/add-message.sh "Grace Hopper" "Hello World"
{{< /tab >}}
{{< tab header="PowerShell" lang="powershell" >}}
docker exec getting-started-postgres psql -U drasi_user -d getting_started -c "INSERT INTO message (""from"", message) VALUES ('Grace Hopper', 'Hello World');"
{{< /tab >}}
{{< /tabpane >}}

Terminal 1 reacts immediately — the filter picks up the new sender and the aggregate ticks up:

```text
[13:06:26] [hello-world-from] + MessageFrom='Grace Hopper'  MessageId=4
[13:06:26] [message-count] ~ Frequency=1  Message='Hello World' -> Frequency=2  Message='Hello World'
```

Try a message that *isn't* `Hello World` (say `bash scripts/add-message.sh "Bob" "Goodbye World"`) and only `message-count` changes — the filter query ignores it.

### Delete a message

Remove a message by its id (the add script prints the `messageid`; message `2` is the seeded `Hello World`):

{{< tabpane persist="header" >}}
{{< tab header="bash / zsh" lang="bash" >}}
bash scripts/delete-message.sh 2
{{< /tab >}}
{{< tab header="PowerShell" lang="powershell" >}}
docker exec getting-started-postgres psql -U drasi_user -d getting_started -c "DELETE FROM message WHERE messageid=2;"
{{< /tab >}}
{{< /tabpane >}}

`hello-world-from` drops that row and `message-count` decrements — a row leaving a result set is a change Drasi reports too.

## How It Works {#how}

The whole demo is a small Python program in `tutorials/getting-started/`: `app.py` runs the engine and prints, and `demo/` holds the queries and configuration.

### The Source

The app installs the Postgres plugins and adds the source, pointing it at the tutorial database:

```python
await drasi.install_plugin("source/postgres")
await drasi.install_plugin("bootstrap/postgres")
await drasi.start()

await drasi.add_source(
    "postgres",
    "messages",
    {
        **POSTGRES,  # host, port, user, password, database
        "sslMode": "prefer",
        "tables": ["public.message"],
        "tableKeys": [{"table": "message", "keyColumns": ["messageid"]}],
        "slotName": "drasi_getting_started_slot",
        "publicationName": "drasi_getting_started_pub",
    },
    bootstrap={"kind": "postgres", **POSTGRES},
)
```

The source uses **logical replication (CDC)** to stream changes from the `message` table; the `bootstrap` provider loads the rows that already exist when the query starts. The table name is lower-case so the node label Drasi sees matches the queries: `(m:message)`.

### The Three Queries

They build up in complexity.

**Filter** — `hello-world-from` returns only messages whose text is exactly `Hello World`, with who sent them:

```cypher
MATCH (m:message)
WHERE m.message = 'Hello World'
RETURN m.messageid AS MessageId, m.from AS MessageFrom
```

**Aggregation** — `message-count` groups by message text and counts. Like SQL's `GROUP BY`, the non-aggregated `Message` travels alongside `count(m)`, and Drasi maintains the counts **incrementally** — one insert bumps exactly one row:

```cypher
MATCH (m:message)
RETURN m.message AS Message, count(m) AS Frequency
```

**Absence of change** — `inactive-people` finds senders who have gone quiet. It takes each sender's most recent message time and flags them once it is more than 20 seconds ago. `drasi.trueLater` **schedules a future re-evaluation** so a sender appears the instant they cross the threshold, not only when some other change happens:

```cypher
MATCH (m:message)
WITH m.from AS MessageFrom, max(drasi.changeDateTime(m)) AS LastMessageTimestamp
WHERE LastMessageTimestamp <= datetime.realtime() - duration({ seconds: 20 })
   OR drasi.trueLater(
        LastMessageTimestamp <= datetime.realtime() - duration({ seconds: 20 }),
        LastMessageTimestamp + duration({ seconds: 20 })
      )
RETURN MessageFrom, LastMessageTimestamp
```

`drasi.changeDateTime(m)` exposes the wall-clock time of each change and `datetime.realtime()` is the current time, so this needs no extra timestamp bookkeeping in your app.

### The Python Reaction

Instead of a dashboard or an SSE stream, a single **Python reaction** subscribed to all three queries prints each change to the console:

```python
def on_change(event):
    query_id = event["query_id"]
    for diff in event["results"]:
        if diff["type"] == "ADD":
            print(f"[{query_id}] + {diff['data']}")
        elif diff["type"] == "DELETE":
            print(f"[{query_id}] - {diff['data']}")
        else:  # UPDATE
            print(f"[{query_id}] ~ {diff['before']} -> {diff['after']}")


await drasi.add_python_reaction("console", [q.id for q in QUERIES], on_change)
```

`type` tells you which of `data`, or `before` and `after`, a diff carries. After registering the reaction the app just `await asyncio.Event().wait()`s, so it stays in the foreground printing changes until you press Ctrl+C. See [Python reactions](../../guides/python-reactions/) for the full callback contract, or [Streaming results](../../guides/streaming/) to consume the same changes as an async iterator instead.

## Clean Up {#cleanup}

When you're finished, stop the app with **Ctrl+C** in Terminal 1, then remove the database container:

{{< tabpane persist="header" >}}
{{< tab header="bash / zsh" lang="bash" >}}
# Stop the container, keep data
bash scripts/cleanup.sh

# Stop the container and delete the data volume
bash scripts/cleanup.sh --volumes
{{< /tab >}}
{{< tab header="PowerShell" lang="powershell" >}}
# Stop the container, keep data
powershell -ExecutionPolicy Bypass -File scripts/cleanup.ps1

# Stop the container and delete the data volume
powershell -ExecutionPolicy Bypass -File scripts/cleanup.ps1 -RemoveVolumes
{{< /tab >}}
{{< /tabpane >}}

## What You Learned {#summary}

- **Sources** connect Drasi to live data — here, PostgreSQL via Change Data Capture, in a few lines of Python.
- **Continuous Queries** let you **filter**, **aggregate**, and even detect the **absence** of change (with the temporal `drasi.trueLater`) — all kept current automatically, with no polling.
- A **Python reaction** turned every query change into console output; the same callback could call an API, write a file, or push a notification instead.

From here, try the [Building Comfort](../building-comfort/) and [Curbside Pickup](../curbside-pickup/) tutorials, which add synthetic joins, cross-database joins, and a live Streamlit UI.
