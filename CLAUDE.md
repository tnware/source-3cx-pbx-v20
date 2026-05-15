# source-3cx-pbx-v20

Custom Airbyte source connector for **3CX PBX v20** (XAPI). Written
with the Python connector CDK in the declarative + Python-streams
hybrid pattern.

## What it produces

Three streams, landed by Airbyte into the destination's `public.*`
schema (in our deployment, that's the test-db CNPG cluster):

| Stream | 3CX endpoint | Sync mode |
|---|---|---|
| `queues` | `/xapi/v1/Queues` | full_refresh |
| `threecx_users` | `/xapi/v1/Users` | full_refresh |
| `call_log_data` | `Pbx.GetCallLogData` (OData function) | incremental, cursor: `segment_start_time_utc` |

Call log data uses 1-day chunked windows with a UTC-aware datetime
floor (`if chunk_start.tzinfo is None: chunk_start = chunk_start.replace(tzinfo=timezone.utc)`)
because the bare `YYYY-MM-DD` state cursor parses naive on Python 3.10
and comparing naive vs aware datetimes blows up.

## Place in the pipeline

```
3CX XAPI ──► [this connector] ──► Airbyte ──► test-db.public.threecx_*
                                                      │
                                                      ▼
                                         pwr-dwh stg_threecx__* models
```

## Sibling repos

- **tnware/pwr-dwh** — the dbt warehouse downstream. The
  `stg_threecx__*` view models in `models/staging/threecx/` read this
  connector's tables verbatim. Any rename/schema change here must be
  paired with a corresponding staging-layer change there. The
  `snap_threecx_users.sql` SCD2 snapshot in pwr-dwh tracks
  reassignment of extensions to new hires over time, which depends on
  this connector's `threecx_users` stream.
- **PowerCTS/k8s-cluster** — Airbyte itself runs in the cluster's
  `airbyte` namespace. This connector is registered there as a custom
  Docker source by image reference; the running Airbyte deployment
  pulls the image we publish to GHCR by release. (Local clone is
  named `cts-k8s-cluster`; remote repo name is `k8s-cluster`.)
- **tnware/source-customer-thermometer** — sibling Airbyte source,
  same release pattern, same overall destination database.

## Release flow

Conventional Commits → release-please opens a release PR on each main
merge. Merging the release PR cuts a tag, the `release-please.yml`
workflow's inline `publish-image` job builds + pushes the versioned
image to `ghcr.io/tnware/source-3cx-pbx-v20`. The Airbyte UI's
connector definition gets bumped to the new tag by hand (or by a
Renovate config inside Airbyte if/when that's set up).

## Conventions

- The connector is **PowerCTS-agnostic**: don't hardcode tenant names,
  extension ranges, or specific group IDs. We made this generic on
  purpose.
- 3CX's `/Users` endpoint dies on `$top` values much above 100; the
  `USERS_PAGE_SIZE = 100` constant exists for that reason — don't
  raise it.
- `$select` projections also tend to 400 on 3CX. Prefer fetching the
  full object and slicing in Python.

## Maintenance contract for this file

This file is repo memory for future Claude instances. Two duties:

1. **Keep it in sync with reality.** If a stream is added/removed,
   pagination quirks change, the cursor field changes, the GHCR image
   name changes, or any sibling-repo coupling shifts — update this
   file in the same change that causes the drift.
2. **Cross-corroborate across sibling repos.** Schema/stream changes
   here propagate into `tnware/pwr-dwh`'s `stg_threecx__*` models —
   update that repo's CLAUDE.md in the same coordinated work.
   Cluster-side wiring (Airbyte connector image tag) is in
   `PowerCTS/k8s-cluster` but that repo doesn't carry a CLAUDE.md
   by design; this file (and pwr-dwh's) is the authoritative
   description of the data flow. The connector-side CLAUDE.md files
   are `.gitignored` (this repo's contents are IP-ish), so the only
   authoritative copies live on disk — be careful not to lose them
   when re-cloning.
