# Measuring success: `drasi-lib` adoption metrics

The success metric for the Python binding is **growth in downloads and
public dependents** after `drasi-lib` is published to PyPI. This maps directly
to the parent epic: the package must be available on PyPI, and we need evidence
that new and active Python developers are trying it and, eventually, declaring
it as a dependency.

Download counts are useful as a directional signal, not as a precise user count.
They include automated installs from CI, release validation, notebooks and fresh
environments. They can also be distorted by mirrors, caching and repeated
installs in build systems. Treat a sustained trend as meaningful; do not treat a
single spike as proof of adoption.

> The first release, `0.1.0`, was published on 2026-07-28, so there is very
> little history yet. Expect the first weeks of numbers to be dominated by CI,
> release validation and mirrors rather than by people.

## What to track

| Metric | Source | Why it matters |
| --- | --- | --- |
| Downloads, last day/week/month | pypistats / PyPI BigQuery | Fast signal that people or automation can install the package. |
| Downloads by day | PyPI BigQuery | Shows whether usage is sustained or a one-off release spike. |
| Downloads by Python version, platform and installer | pypistats / PyPI BigQuery | Helps distinguish real users from release automation and shows compatibility demand. |
| Public dependents | libraries.io, GitHub dependency graph where available | Shows that other projects are building on the package rather than only trying it. |

## Download statistics

### pypistats

[pypistats](https://pypistats.org/) is the lightest way to read PyPI download
statistics. It exposes a web page and JSON API, and the
[`pypistats`](https://pypi.org/project/pypistats/) CLI formats the same data for
copying into issues or release notes.

```bash
python -m pip install --upgrade pypistats

# Last day, week and month. pypistats excludes known mirrors.
pypistats recent drasi-lib --format json

# Python version mix for the previous complete month.
pypistats python_minor drasi-lib --last-month --format md

# Operating system mix for the previous complete month.
pypistats system drasi-lib --last-month --format md
```

The package page will be:

```text
https://pypistats.org/packages/drasi-lib
```

pypistats keeps time-series data for the last 180 days and updates once per day.
That is enough for a lightweight monthly report, but use BigQuery for older data
or for fields that pypistats does not expose.

### PyPI BigQuery dataset

PyPI download events are published to the public BigQuery table
`bigquery-public-data.pypi.file_downloads`. Use it when the question needs more
control than pypistats gives, such as filtering by installer, inspecting Python
versions or separating CI-heavy periods from organic usage.

Daily downloads for an explicit month:

```sql
SELECT
  DATE(timestamp) AS download_date,
  COUNT(*) AS downloads
FROM `bigquery-public-data.pypi.file_downloads`
WHERE file.project = 'drasi-lib'
  AND DATE(timestamp) BETWEEN '2026-08-01' AND '2026-08-31'
GROUP BY download_date
ORDER BY download_date;
```

The same query, restricted to installs reported by `pip`:

```sql
SELECT
  DATE(timestamp) AS download_date,
  COUNT(*) AS downloads
FROM `bigquery-public-data.pypi.file_downloads`
WHERE file.project = 'drasi-lib'
  AND DATE(timestamp) BETWEEN '2026-08-01' AND '2026-08-31'
  AND details.installer.name = 'pip'
GROUP BY download_date
ORDER BY download_date;
```

Break down the previous complete month by Python version, platform and
installer:

```sql
SELECT
  REGEXP_EXTRACT(details.python, r'^([^\.]+\.[^\.]+)') AS python_version,
  details.system.name AS system_name,
  details.installer.name AS installer_name,
  COUNT(*) AS downloads
FROM `bigquery-public-data.pypi.file_downloads`
WHERE file.project = 'drasi-lib'
  AND DATE(timestamp) >= DATE_TRUNC(DATE_SUB(CURRENT_DATE(), INTERVAL 1 MONTH), MONTH)
  AND DATE(timestamp) < DATE_TRUNC(CURRENT_DATE(), MONTH)
GROUP BY python_version, system_name, installer_name
ORDER BY downloads DESC;
```

Practical caveats:

- BigQuery is not part of PyPI itself. It requires a Google Cloud project, and
  large scans can cost money. Always constrain queries by `file.project` and a
  date range before adding more fields.
- The public data is not real time. For routine reporting, run queries after the
  month has closed rather than during the first hours of the next day.
- `details.installer.name` is useful for excluding known mirrors and noisy
  automation. `pip` is the default headline view; keep an unfiltered total as a
  diagnostic comparison.
- CI downloads are still counted even when the installer is `pip`, so compare
  release weeks with quieter weeks before drawing conclusions.

## Dependents

PyPI does not expose an npm-style dependents tab or reverse-dependency API for a
package. Track public dependents through secondary indexes instead:

- [libraries.io](https://libraries.io/pypi/drasi-lib), once it has indexed the
  package. Its project API reports `dependents_count` and
  `dependent_repos_count`, but API calls require a libraries.io API key.
- GitHub's dependency graph and **Used by** views, where available. These count
  repositories GitHub can analyse, not every PyPI project, and private
  repositories are not visible.

Record dependents as a small integer snapshot, not as an exhaustive census.
Expect it to remain zero for a while after the first release; downloads are the
earlier signal, dependents are the stronger signal.

## Baseline

Create the baseline after the first successful PyPI release and after the first
full calendar month with download data. Record enough context that future
reports can explain changes rather than only quote a number.

| Field | Value to record |
| --- | --- |
| Package name | `drasi-lib` |
| Import name | `drasi` |
| First PyPI version | The first version published to PyPI |
| First publish date | UTC date from PyPI release metadata |
| Baseline month | First complete calendar month after publish |
| Downloads, last day/week/month | `pypistats recent drasi-lib --format json` |
| Downloads in baseline month | BigQuery count, with and without `details.installer.name = 'pip'` |
| Top Python versions | `pypistats python_minor drasi-lib --last-month --format md` |
| Top platforms | `pypistats system drasi-lib --last-month --format md` |
| Dependents | libraries.io `dependents_count` and `dependent_repos_count`, plus GitHub **Used by** count if shown |
| Notes | Release validation, CI changes, docs launches or demos that may explain spikes |

Keep the baseline in the issue or release tracking notes rather than in this
file, so the documentation remains the process and the numbers remain the
reporting record.

## Reporting cadence

A lightweight cadence is enough:

1. After each release, confirm the PyPI project page and pypistats page resolve.
2. Monthly, after the previous month has closed, capture downloads, Python
   version mix, platform mix and dependents.
3. Quarterly, summarise the trend in the epic or team planning notes: last-month
   downloads, three-month direction, dependents and any caveats.
4. If a number jumps unexpectedly, check installer, Python version and platform
   breakdowns before reporting it as adoption.

## Difference from the Node.js binding

The Node.js binding can use npm's public download API and npm's package page for
both downloads and dependents. PyPI differs in two important ways: detailed
download reporting lives in pypistats and the PyPI BigQuery public dataset, and
PyPI does not expose public dependents directly. For Python, the download
process is therefore slightly more BigQuery-oriented, and dependents must come
from libraries.io and GitHub's dependency graph rather than PyPI itself.
