# source-3cx-xapi

Airbyte custom source connector for the [3CX PBX Management API](https://www.3cx.com/docs/manual/api/) (XAPI).

## Streams

| Stream                          | Sync mode               | Notes                                                                                                  |
| ------------------------------- | ----------------------- | ------------------------------------------------------------------------------------------------------ |
| `call_log_data`                 | incremental + full      | Per-call records. Incremental by `start_time`. Fetched in 7-day chunks to avoid request timeouts.       |
| `queue_performance_overview`    | full refresh            | Per-extension, per-queue stats over a rolling lookback window.                                          |
| `agents_in_queue_statistics`    | full refresh            | Per-agent, per-queue stats. Sliced by queue DN (queue list cached per sync).                            |
| `users`                         | full refresh            | 3CX user / extension master from `/xapi/v1/Users`. Used to join Zendesk users to 3CX activity by email. |

## Authentication

OAuth2 client-credentials grant against `https://<fqdn>/connect/token`.
Create the client in **3CX → Admin → Integrations → API**:

1. Click **Add new application**
2. Save the resulting **Client ID** and **Client Secret**
3. The client only needs read scope; no write permissions required

## Configuration

| Field             | Required | Description                                                                                                 |
| ----------------- | -------- | ----------------------------------------------------------------------------------------------------------- |
| `fqdn`            | yes      | Hostname of the 3CX server, e.g. `pbx.example.com`. No protocol prefix.                                     |
| `client_id`       | yes      | OAuth2 client ID from the XAPI application.                                                                 |
| `client_secret`   | yes      | OAuth2 client secret. Marked as Airbyte secret.                                                             |
| `start_date`      | yes      | `YYYY-MM-DD`. First date to pull `call_log_data` from on the first sync. Cursor advances from there.        |
| `lookback_months` | no       | Default 2. Rolling window for the queue-aggregate streams. Doesn't affect `call_log_data` or `users`.        |

## Build + push

The image is built and pushed by `.github/workflows/image.yml` on every
push to `main` (and on tags). To build locally:

```bash
docker build -t ghcr.io/tnware/source-3cx-xapi:dev .
```

The image is built on top of `airbyte/python-connector-base` and uses
Python 3.11.

## Local testing

Standard Airbyte connector entrypoints:

```bash
# Spec
python -m source_3cx_xapi spec

# Connection check
python -m source_3cx_xapi check --config /path/to/secrets/config.json

# Catalog discovery
python -m source_3cx_xapi discover --config /path/to/secrets/config.json

# Read a stream
python -m source_3cx_xapi read \
  --config /path/to/secrets/config.json \
  --catalog /path/to/integration_tests/configured_catalog.json
```

Example `config.json`:

```json
{
  "fqdn": "pbx.example.com",
  "client_id": "...",
  "client_secret": "...",
  "start_date": "2024-01-01",
  "lookback_months": 2
}
```

## Pointing Airbyte at this connector

In the Airbyte UI:

1. **Settings → Sources → New connector**
2. **Add a new Docker connector**
3. Image name: `ghcr.io/tnware/source-3cx-xapi`
4. Image tag: pick a published tag (see [Releases](https://github.com/tnware/source-3cx-xapi/releases))

If the image is in a private GHCR package, set up an `imagePullSecrets`
entry on the Airbyte worker pod referencing a GHCR PAT.

## Releases & commit style

Releases are automated by [release-please](https://github.com/googleapis/release-please).
Commit to `main` using [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add new Foo endpoint        → minor bump (0.4.0 → 0.5.0)
fix:  handle null EmailAddress    → patch bump (0.4.0 → 0.4.1)
chore: bump action versions       → no release (hidden from changelog)
feat!: drop deprecated cursor     → major bump (note the !)
```

Release-please watches `main` and maintains a rolling **Release PR** that:
- Bumps `pyproject.toml` `version` and `metadata.yaml` `dockerImageTag`
  in lockstep
- Appends a categorized entry to `CHANGELOG.md`
- When merged, cuts a `vX.Y.Z` tag and a GitHub Release. The
  `image.yml` workflow picks up the tag and builds + pushes the
  versioned image.

Don't hand-edit versions or the CHANGELOG — release-please owns those.

## CHANGELOG

See [CHANGELOG.md](CHANGELOG.md).

## License

MIT — see [LICENSE](LICENSE).
