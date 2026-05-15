# Changelog

All notable changes to this connector are documented here. Versions
follow [Semantic Versioning](https://semver.org/) and are managed by
[release-please](https://github.com/googleapis/release-please) — see
the `Releases & commit style` section in the README.

## [0.5.6](https://github.com/tnware/source-3cx-pbx-v20/compare/v0.5.5...v0.5.6) (2026-05-15)


### Bug Fixes

* emit AgentsInQueueStatistics per month, not per window ([#27](https://github.com/tnware/source-3cx-pbx-v20/issues/27)) ([ec8561d](https://github.com/tnware/source-3cx-pbx-v20/commit/ec8561d57054eb616136cc7d90a8953da1f6aa2f))

## [0.5.5](https://github.com/tnware/source-3cx-pbx-v20/compare/v0.5.4...v0.5.5) (2026-05-15)


### Bug Fixes

* CallLogData naive datetime crash; Queues 400 on $top=200/$select ([#25](https://github.com/tnware/source-3cx-pbx-v20/issues/25)) ([c82b7b7](https://github.com/tnware/source-3cx-pbx-v20/commit/c82b7b7a21ffcb5dd5bd931062f850c20b0347e7))

## [0.5.4](https://github.com/tnware/source-3cx-pbx-v20/compare/v0.5.3...v0.5.4) (2026-05-14)


### Features

* replace queue_performance_overview with a /Queues-backed queues stream ([#12](https://github.com/tnware/source-3cx-pbx-v20/issues/12)) ([1d6fe1c](https://github.com/tnware/source-3cx-pbx-v20/commit/1d6fe1c8db6302668e3cf65ca567c1bc41ebd5eb))

## [0.5.3](https://github.com/tnware/source-3cx-pbx-v20/compare/v0.5.2...v0.5.3) (2026-05-14)


### Bug Fixes

* lower /Users page size to 100 ([#10](https://github.com/tnware/source-3cx-pbx-v20/issues/10)) ([75d54b5](https://github.com/tnware/source-3cx-pbx-v20/commit/75d54b582ebe8eaaf38ca520e04e07a6d26d313d))

## [0.5.2](https://github.com/tnware/source-3cx-pbx-v20/compare/v0.5.1...v0.5.2) (2026-05-14)


### Bug Fixes

* version-tag the connector image on release ([#7](https://github.com/tnware/source-3cx-pbx-v20/issues/7)) ([2f5a77e](https://github.com/tnware/source-3cx-pbx-v20/commit/2f5a77e56f6d1bbfa9b76d619f9f1face01b5c0d))

## [0.5.1](https://github.com/tnware/source-3cx-pbx-v20/compare/v0.5.0...v0.5.1) (2026-05-14)


### Bug Fixes

* accept day component in parse_iso_duration ([b292aa9](https://github.com/tnware/source-3cx-pbx-v20/commit/b292aa9f81d30f49cfb1c4e8fe8f4ae48c8f8cb2))
* accept day component in parse_iso_duration ([9538a31](https://github.com/tnware/source-3cx-pbx-v20/commit/9538a319343eaefb165ed133558307d12b322d59))


### Documentation

* document the four observed Direction values ([#5](https://github.com/tnware/source-3cx-pbx-v20/issues/5)) ([7f15704](https://github.com/tnware/source-3cx-pbx-v20/commit/7f157042445e6e938f2ee98d6442b5e623c6a98f))
* note that start_date is interpreted as midnight UTC ([#6](https://github.com/tnware/source-3cx-pbx-v20/issues/6)) ([01d4ce6](https://github.com/tnware/source-3cx-pbx-v20/commit/01d4ce63d884d1de9225a30ceb05cf14eb4af7a7))

## [0.5.0](https://github.com/tnware/source-3cx-pbx-v20/compare/v0.4.0...v0.5.0) (2026-05-14)


### ⚠ BREAKING CHANGES

* Docker image path, Python package import, and connector definitionId all change. No external consumers yet (only configured locally), so blast radius is the local Airbyte connection that hasn't been wired up.

### Features

* rename connector to source-3cx-pbx-v20 ([61f6308](https://github.com/tnware/source-3cx-pbx-v20/commit/61f6308b3dd0eefd554b4c6e197566835d945722))

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
