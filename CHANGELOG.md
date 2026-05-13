# Changelog

All notable changes to this connector are documented here. Versions follow
[Semantic Versioning](https://semver.org/) — bump the minor on new streams or
backwards-incompatible field changes; patch on bug fixes only.

## [Unreleased]

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
  `ghcr.io/powercts/source-3cx-xapi`.

### Fixed
- Version sync: `pyproject.toml` and `metadata.yaml` now agree
  (previously 0.1.2 vs 0.1.3).

## [0.1.3] — earlier
- Initial extraction from the PowerCTS reporting monorepo.
- Three streams: `call_log_data`, `queue_performance_overview`,
  `agents_in_queue_statistics`.
- 7-day chunking on `call_log_data` to fix request timeouts on large
  backfills.
