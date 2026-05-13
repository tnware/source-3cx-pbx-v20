# Changelog

All notable changes to this connector are documented here. Versions
follow [Semantic Versioning](https://semver.org/) and are managed by
[release-please](https://github.com/googleapis/release-please) — see
the `Releases & commit style` section in the README.

## [0.4.0] — 2026-05-13

### Fixed
- `metadata.yaml` `dockerRepository` corrected from
  `ghcr.io/powercts/source-3cx-xapi` to `ghcr.io/tnware/source-3cx-xapi`
  to match the actual GHCR location (the GHA workflow uses
  `github.repository_owner` which resolves to `tnware`). Published
  v0.3.0 images landed at the correct path; only the metadata pointer
  was wrong.
- README references updated to the correct GHCR path and the correct
  GitHub repo URL.

## [0.3.0] — 2026-05-13

### Added
- **Pytest suite** (42 tests) covering pure helpers (`parse_iso_duration`,
  `_parse_iso_datetime`, `_start_of_month_n_ago`, `_period_from_config`),
  the `ThreeCXClient` HTTP layer (auth, 401 re-auth, 429 backoff,
  response-shape validation, pagination), `CallLogData` cursor logic,
  `Users` stream mapping, and the queue-list cache.
- CI gate: `image.yml` now runs `pytest` in a `test` job that the
  `build` job depends on. Failing tests block the image push.
- `[project.optional-dependencies] dev = ["pytest>=7.0", "responses>=0.23"]`
  in pyproject.toml.

### Changed
- **Enriched all four JSON Schemas**: every field has a `description`;
  timestamp fields use `format: date-time` + `airbyte_type:
  timestamp_with_timezone`; date fields use `format: date` +
  `airbyte_type: date`. Airbyte's typed destination will now create
  proper `TIMESTAMPTZ` / `DATE` Postgres columns instead of `TEXT`,
  removing the need for downstream type casts.

## [0.2.0] — 2026-05-13

### Added
- **New stream `users`** sourced from `/xapi/v1/Users`. Emits one row per
  3CX extension with `extension`, `email`, `display_name`, `first_name`,
  `last_name`, `is_enabled`, `auth_id`, `mobile_number`. Enables joining
  Zendesk users to 3CX activity by email.
- HTTP timeout (60s default) on all client calls; previously the auth
  call and report endpoints had no timeout and could hang indefinitely.
- Response-shape validation in `_get`: rejects non-dict bodies and
  non-list `value` fields with a clear error, instead of letting a
  malformed response crash with an obscure `TypeError`.
- Cached queue list across `QueuePerformanceOverview` and
  `AgentsInQueueStatistics` within a single sync. Previously the queue
  list was fetched up to three times per sync.
- Documented in-stream that `call_log_data.end_time` is always `NULL`
  by design (3CX's report API doesn't expose a call-end timestamp).

### Changed
- Datetime parsing in `CallLogData.get_updated_state` now falls back to
  string-sort comparison if `fromisoformat` rejects the format; ISO 8601
  strings sort lexicographically, so this is safe.
- `Source3cxXapi.streams()` now returns four streams instead of three.
- Bumped `dockerRepository` in metadata.yaml to
  `ghcr.io/powercts/source-3cx-xapi` (corrected to `tnware/source-3cx-xapi` in v0.4.0;
  renamed to `tnware/source-3cx-pbx-v20` in the post-0.4.0 rename).

### Fixed
- Version sync: `pyproject.toml` and `metadata.yaml` now agree
  (previously 0.1.2 vs 0.1.3).

## [0.1.3] — earlier
- Initial extraction from the PowerCTS reporting monorepo.
- Three streams: `call_log_data`, `queue_performance_overview`,
  `agents_in_queue_statistics`.
- 7-day chunking on `call_log_data` to fix request timeouts on large
  backfills.
