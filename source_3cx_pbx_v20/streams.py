"""Stream implementations for the 3CX XAPI Airbyte connector.

Four streams:

- ``CallLogData`` — incremental by ``start_time`` cursor, OData $top/$skip,
  fetched in 7-day chunks to keep individual requests under the Airbyte
  workload timeout.
- ``QueuePerformanceOverview`` — full refresh over a rolling lookback window.
- ``AgentsInQueueStatistics`` — full refresh, sliced per queue DN. Queue
  list is cached on the instance so ``stream_slices`` and ``read_records``
  don't both pay for it.
- ``Users`` — full refresh of the 3CX extension/user master.

Output field names match the destination column names expected by the
downstream dbt warehouse so the staging models need no field-name
translation.
"""

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Optional

from airbyte_cdk.models import SyncMode
from airbyte_cdk.sources.streams import Stream

from .client import ThreeCXClient, parse_iso_duration

log = logging.getLogger(__name__)

_SCHEMAS_DIR = os.path.join(os.path.dirname(__file__), "schemas")


def _load_schema(name: str) -> Mapping[str, Any]:
    """Load a JSON schema by stream name."""
    with open(os.path.join(_SCHEMAS_DIR, f"{name}.json")) as f:
        return json.load(f)


def _parse_iso_datetime(value: str) -> Optional[datetime]:
    """Best-effort ISO 8601 datetime parsing.

    Accepts ``YYYY-MM-DDTHH:MM:SSZ`` (3CX's standard format) and the
    equivalent with explicit ``+00:00`` offset. Returns None on failure
    rather than raising, so caller can fall back to string comparison.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        return None


def _start_of_month_n_ago(n: int) -> date:
    """Return the first day of the month N months ago (relative to today)."""
    today = date.today()
    month = today.month - n
    year = today.year
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1)


def _period_from_config(config: Mapping[str, Any]) -> tuple[datetime, datetime]:
    """Return (period_from, period_to) for full-refresh queue streams.

    period_from = first day of the month ``lookback_months`` ago
    period_to   = end of today
    """
    lookback = int(config.get("lookback_months", 2))
    period_from = datetime.combine(_start_of_month_n_ago(lookback), datetime.min.time())
    period_to = datetime.combine(date.today(), datetime.max.time().replace(microsecond=0))
    return period_from, period_to


def _build_client(config: Mapping[str, Any]) -> ThreeCXClient:
    return ThreeCXClient(
        fqdn=config["fqdn"],
        client_id=config["client_id"],
        client_secret=config["client_secret"],
    )


# ---------------------------------------------------------------------------
# CallLogData — incremental with start_time cursor
# ---------------------------------------------------------------------------

class CallLogData(Stream):
    """Per-call records, ingested incrementally by start_time."""

    primary_key = "call_id"
    cursor_field = "start_time"

    # Fetch at most this many days per API call. Keeps each request small
    # enough to complete within the Airbyte container timeout regardless
    # of call volume. 7 days is a safe ceiling — a full-month backfill
    # becomes 4-5 calls instead of one giant request that historically
    # caused incomplete / failed syncs.
    _CHUNK_DAYS = 7

    def __init__(self, config: Mapping[str, Any]):
        super().__init__()
        self._client = _build_client(config)
        self._start_date = config["start_date"]

    @property
    def source_defined_cursor(self) -> bool:
        return True

    @property
    def supported_sync_modes(self):
        return [SyncMode.incremental, SyncMode.full_refresh]

    def get_updated_state(
        self, current_stream_state: Mapping[str, Any], latest_record: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        current_cursor = current_stream_state.get(self.cursor_field) or ""
        latest_cursor = latest_record.get(self.cursor_field) or ""

        current_dt = _parse_iso_datetime(current_cursor)
        latest_dt = _parse_iso_datetime(latest_cursor)

        if current_dt and latest_dt:
            winner = max(current_dt, latest_dt)
            return {self.cursor_field: winner.strftime("%Y-%m-%dT%H:%M:%SZ")}

        # Fallback: pick whichever non-empty string is later by string sort.
        # Safe because ISO 8601 strings sort lexicographically.
        return {self.cursor_field: max(current_cursor, latest_cursor) or current_cursor}

    def read_records(
        self,
        sync_mode: SyncMode,
        cursor_field: list[str] = None,
        stream_slice: Mapping[str, Any] = None,
        stream_state: Mapping[str, Any] = None,
    ) -> Iterable[Mapping[str, Any]]:
        state = stream_state or {}
        cursor_value = state.get(self.cursor_field, self._start_date)

        # Cursor may be either an ISO datetime ("2026-05-13T14:30:00Z") or a
        # bare date ("2026-05-13"). Normalize to a datetime; default missing
        # times to start-of-day UTC.
        chunk_start = _parse_iso_datetime(cursor_value)
        if chunk_start is None:
            chunk_start = _parse_iso_datetime(f"{cursor_value}T00:00:00+00:00")
        if chunk_start is None:
            raise ValueError(
                f"CallLogData cursor value could not be parsed as a date or "
                f"datetime: {cursor_value!r}"
            )

        period_to = datetime.now(timezone.utc)

        while chunk_start < period_to:
            chunk_end = min(chunk_start + timedelta(days=self._CHUNK_DAYS), period_to)
            from_str = chunk_start.strftime("%Y-%m-%dT%H:%M:%SZ")
            to_str = chunk_end.strftime("%Y-%m-%dT%H:%M:%SZ")

            log.info("CallLogData: fetching chunk %s → %s", from_str, to_str)
            raw_records = self._client.get_call_log_data(from_str, to_str)
            log.info("CallLogData: chunk returned %d records", len(raw_records))

            for r in raw_records:
                raw_talking = r.get("TalkingDuration", "")
                raw_ringing = r.get("RingingDuration", "")
                talk_seconds = parse_iso_duration(raw_talking)
                ringing_seconds = parse_iso_duration(raw_ringing)
                total_duration = ringing_seconds + talk_seconds

                # Direction is an unconstrained string in the XAPI spec
                # (Pbx.CallLogData has no enum on this field). Values
                # observed empirically against PowerCTS data:
                #   "Inbound" / "Inbound Queue" — external caller; agent
                #     is on the destination side.
                #   "Outbound" — agent dials out; agent is on the source.
                #   "Internal" — extension-to-extension; both sides are
                #     agents. Attribute to the caller (SourceDn);
                #     downstream can filter on `direction = 'Internal'`
                #     to exclude or split if a model wants different
                #     handling.
                direction = r.get("Direction", "") or ""
                is_inbound = direction.lower() in ("inbound", "inbound queue")

                yield {
                    "call_id": str(r.get("MainCallHistoryId") or r.get("CallHistoryId", "")),
                    "seg_id": str(r.get("SegmentId", "")),
                    "call_type": r.get("CallType"),
                    "direction": direction,
                    "caller_number": r.get("SourceCallerId"),
                    "caller_name": r.get("SourceDisplayName"),
                    "callee_number": r.get("DestinationCallerId"),
                    "callee_name": r.get("DestinationDisplayName"),
                    "queue_name": None,
                    "agent_extension": (
                        r.get("DestinationDn") if is_inbound else r.get("SourceDn")
                    ),
                    "agent_name": (
                        r.get("DestinationDisplayName")
                        if is_inbound
                        else r.get("SourceDisplayName")
                    ),
                    "destination_dn": r.get("DestinationDn"),
                    "destination_display_name": r.get("DestinationDisplayName"),
                    "source_dn": r.get("SourceDn"),
                    "source_display_name": r.get("SourceDisplayName"),
                    "start_time": r.get("StartTime"),
                    # 3CX's GetCallLogData OData function doesn't surface a
                    # call-end timestamp; it's derived from StartTime + the
                    # total duration. We emit NULL rather than synthesizing
                    # it so downstream models can compute it consistently
                    # (or omit if they don't need it).
                    "end_time": None,
                    "duration_seconds": total_duration,
                    "talk_time_seconds": talk_seconds,
                    "is_answered": r.get("Answered", False),
                    "status": r.get("Status"),
                    "raw_talking_duration": raw_talking,
                }

            chunk_start = chunk_end

    def get_json_schema(self) -> Mapping[str, Any]:
        return _load_schema("call_log_data")


# ---------------------------------------------------------------------------
# Shared queue-list cache for the two queue-driven streams
# ---------------------------------------------------------------------------

class _QueueListMixin:
    """Adds a per-instance cache of the queue list.

    Both ``QueuePerformanceOverview`` and ``AgentsInQueueStatistics`` need
    the queue list to do their work; previously each fetched it
    independently and ``AgentsInQueueStatistics`` even fetched it twice
    (in ``stream_slices`` and again in ``read_records``). Cache it.
    """

    def _queue_list(self) -> list[dict]:
        if not hasattr(self, "_queue_cache") or self._queue_cache is None:
            period_from, period_to = _period_from_config(self._config)
            self._queue_cache = self._client.get_queue_performance_overview(
                period_from, period_to
            )
        return self._queue_cache


# ---------------------------------------------------------------------------
# QueuePerformanceOverview — full refresh
# ---------------------------------------------------------------------------

class QueuePerformanceOverview(Stream, _QueueListMixin):
    """Per-extension, per-queue stats over a rolling lookback window."""

    primary_key = ["queue_dn", "extension_dn", "period_start", "period_end"]

    def __init__(self, config: Mapping[str, Any]):
        super().__init__()
        self._client = _build_client(config)
        self._config = config
        self._queue_cache: Optional[list[dict]] = None

    @property
    def supported_sync_modes(self):
        return [SyncMode.full_refresh]

    def read_records(
        self,
        sync_mode: SyncMode,
        cursor_field: list[str] = None,
        stream_slice: Mapping[str, Any] = None,
        stream_state: Mapping[str, Any] = None,
    ) -> Iterable[Mapping[str, Any]]:
        period_from, period_to = _period_from_config(self._config)
        period_start_str = period_from.date().isoformat()
        period_end_str = period_to.date().isoformat()

        for r in self._queue_list():
            yield {
                "queue_dn": r.get("QueueDn", ""),
                "queue_display_name": r.get("QueueDisplayName"),
                "extension_dn": r.get("ExtensionDn", ""),
                "extension_display_name": r.get("ExtensionDisplayName"),
                "answered_count": r.get("ExtensionAnsweredCount", 0),
                "talk_time_seconds": parse_iso_duration(r.get("TalkTime", "")),
                "avg_talk_time_seconds": parse_iso_duration(r.get("AvgTalkTime", "")),
                "period_start": period_start_str,
                "period_end": period_end_str,
            }

    def get_json_schema(self) -> Mapping[str, Any]:
        return _load_schema("queue_performance_overview")


# ---------------------------------------------------------------------------
# AgentsInQueueStatistics — full refresh, sliced by queue DN
# ---------------------------------------------------------------------------

class AgentsInQueueStatistics(Stream, _QueueListMixin):
    """Per-agent, per-queue stats. Queue DNs are discovered dynamically."""

    primary_key = ["agent_dn", "queue_dn", "period_start", "period_end"]

    def __init__(self, config: Mapping[str, Any]):
        super().__init__()
        self._client = _build_client(config)
        self._config = config
        self._queue_cache: Optional[list[dict]] = None

    @property
    def supported_sync_modes(self):
        return [SyncMode.full_refresh]

    def stream_slices(
        self,
        sync_mode: SyncMode,
        cursor_field: list[str] = None,
        stream_state: Mapping[str, Any] = None,
    ) -> Iterable[Optional[Mapping[str, Any]]]:
        """Discover unique queue DNs from the cached queue list."""
        seen: dict[str, str] = {}
        for r in self._queue_list():
            qdn = r.get("QueueDn", "")
            if qdn and qdn not in seen:
                seen[qdn] = r.get("QueueDisplayName", "")
        for qdn, qname in seen.items():
            yield {"queue_dn": qdn, "queue_display_name": qname}

    def read_records(
        self,
        sync_mode: SyncMode,
        cursor_field: list[str] = None,
        stream_slice: Mapping[str, Any] = None,
        stream_state: Mapping[str, Any] = None,
    ) -> Iterable[Mapping[str, Any]]:
        period_from, period_to = _period_from_config(self._config)
        period_start_str = period_from.date().isoformat()
        period_end_str = period_to.date().isoformat()

        queue_dn = (stream_slice or {}).get("queue_dn", "")
        queue_display_name = (stream_slice or {}).get("queue_display_name", "")

        raw = self._client.get_agents_in_queue_statistics(queue_dn, period_from, period_to)
        for r in raw:
            yield {
                "agent_dn": r.get("Dn", ""),
                "agent_display_name": r.get("DnDisplayName", ""),
                "queue_dn": queue_dn,
                "queue_display_name": queue_display_name,
                "period_start": period_start_str,
                "period_end": period_end_str,
                "answered_count": r.get("AnsweredCount", 0),
                "answered_percent": r.get("AnsweredPercent", 0),
                "ring_time_seconds": parse_iso_duration(r.get("RingTime", "")),
                "avg_ring_time_seconds": parse_iso_duration(r.get("AvgRingTime", "")),
                "talk_time_seconds": parse_iso_duration(r.get("TalkTime", "")),
                "avg_talk_time_seconds": parse_iso_duration(r.get("AvgTalkTime", "")),
                "logged_in_time_seconds": parse_iso_duration(r.get("LoggedInTime", "")),
                "lost_count": r.get("LostCount", 0),
            }

    def get_json_schema(self) -> Mapping[str, Any]:
        return _load_schema("agents_in_queue_statistics")


# ---------------------------------------------------------------------------
# Users — full refresh of the 3CX user / extension master
# ---------------------------------------------------------------------------

class Users(Stream):
    """3CX user / extension master.

    Source: ``GET /xapi/v1/Users`` — standard OData collection.

    Used downstream to join Zendesk users (by email) to 3CX activity
    (by extension). Full refresh on every sync since the user list is
    small and changes infrequently.

    Disabled accounts are kept in the output (with ``is_enabled = False``)
    so downstream consumers can decide whether to include them.
    """

    primary_key = "extension"

    def __init__(self, config: Mapping[str, Any]):
        super().__init__()
        self._client = _build_client(config)

    @property
    def supported_sync_modes(self):
        return [SyncMode.full_refresh]

    def read_records(
        self,
        sync_mode: SyncMode,
        cursor_field: list[str] = None,
        stream_slice: Mapping[str, Any] = None,
        stream_state: Mapping[str, Any] = None,
    ) -> Iterable[Mapping[str, Any]]:
        for r in self._client.get_users():
            number = r.get("Number")
            if number is None:
                # No extension number → not useful for the email→extension
                # join; skip rather than emit a row with NULL primary key.
                continue
            yield {
                "extension": str(number),
                "display_name": r.get("DisplayName"),
                "first_name": r.get("FirstName"),
                "last_name": r.get("LastName"),
                "email": r.get("EmailAddress"),
                "is_enabled": r.get("Enabled", True),
                "auth_id": r.get("AuthID"),
                "mobile_number": r.get("MobileNumber"),
            }

    def get_json_schema(self) -> Mapping[str, Any]:
        return _load_schema("users")
