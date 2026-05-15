"""Tests for the 3CX streams — mock the ThreeCXClient where needed."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from airbyte_cdk.models import SyncMode

from source_3cx_pbx_v20.streams import (
    CallLogData,
    Queues,
    AgentsInQueueStatistics,
    Users,
)


CONFIG = {
    "fqdn": "pbx.example.com",
    "client_id": "cid",
    "client_secret": "csecret",
    "start_date": "2026-01-01",
    "lookback_months": 1,
}


# ----------------------------------------------------------------------
# CallLogData.get_updated_state — cursor "winner" logic
# ----------------------------------------------------------------------

class TestCallLogDataCursor:
    @pytest.fixture
    def stream(self):
        with patch("source_3cx_pbx_v20.streams.ThreeCXClient"):
            return CallLogData(CONFIG)

    def test_picks_later_of_two_iso_datetimes(self, stream):
        out = stream.get_updated_state(
            current_stream_state={"start_time": "2026-01-15T09:00:00Z"},
            latest_record={"start_time": "2026-01-16T09:00:00Z"},
        )
        assert out == {"start_time": "2026-01-16T09:00:00Z"}

    def test_picks_later_when_current_is_already_later(self, stream):
        out = stream.get_updated_state(
            current_stream_state={"start_time": "2026-02-15T09:00:00Z"},
            latest_record={"start_time": "2026-01-15T09:00:00Z"},
        )
        assert out == {"start_time": "2026-02-15T09:00:00Z"}

    def test_falls_back_to_string_sort_when_parse_fails(self, stream):
        """If 3CX returns a malformed datetime, fall back to string max
        instead of crashing. ISO 8601 sorts correctly as strings."""
        out = stream.get_updated_state(
            current_stream_state={"start_time": "garbage-1"},
            latest_record={"start_time": "garbage-2"},
        )
        # Both unparseable → string max
        assert out == {"start_time": "garbage-2"}

    def test_uses_existing_state_when_latest_is_empty(self, stream):
        out = stream.get_updated_state(
            current_stream_state={"start_time": "2026-01-15T09:00:00Z"},
            latest_record={},
        )
        assert out["start_time"] == "2026-01-15T09:00:00Z"


# ----------------------------------------------------------------------
# CallLogData.read_records — chunk-walk init
# ----------------------------------------------------------------------

class TestCallLogDataReadRecords:
    def test_bare_date_cursor_does_not_crash_on_naive_aware_comparison(self):
        """Regression: a bare YYYY-MM-DD cursor parses as a naive
        datetime on Python 3.10, which then can't be compared against
        `datetime.now(timezone.utc)`. The chunk-walk loop must
        normalize naive cursor values to UTC before the comparison."""
        with patch("source_3cx_pbx_v20.streams.ThreeCXClient") as MockClient:
            instance = MockClient.return_value
            instance.get_call_log_data.return_value = []

            stream = CallLogData(CONFIG)
            records = list(stream.read_records(
                SyncMode.incremental,
                stream_state={"start_time": "2026-05-13"},
            ))
            assert records == []


# ----------------------------------------------------------------------
# Users stream — record mapping + skip-on-missing-extension
# ----------------------------------------------------------------------

class TestUsersStream:
    def _build_stream(self, mock_users):
        with patch("source_3cx_pbx_v20.streams.ThreeCXClient") as MockClient:
            instance = MockClient.return_value
            instance.get_users.return_value = mock_users
            return Users(CONFIG)

    def test_emits_one_row_per_user(self):
        stream = self._build_stream([
            {
                "Number": 511,
                "DisplayName": "Jane Doe",
                "FirstName": "Jane",
                "LastName": "Doe",
                "EmailAddress": "jane@example.com",
                "Enabled": True,
                "AuthID": "abc-123",
                "MobileNumber": "+15555550101",
            },
        ])
        records = list(stream.read_records(SyncMode.full_refresh))
        assert len(records) == 1
        r = records[0]
        assert r["extension"] == "511"           # stringified
        assert r["email"] == "jane@example.com"
        assert r["display_name"] == "Jane Doe"
        assert r["is_enabled"] is True
        assert r["auth_id"] == "abc-123"

    def test_skips_users_with_no_extension(self):
        stream = self._build_stream([
            {"Number": None, "DisplayName": "No Ext"},
            {"Number": 100, "DisplayName": "Has Ext"},
        ])
        records = list(stream.read_records(SyncMode.full_refresh))
        assert len(records) == 1
        assert records[0]["extension"] == "100"

    def test_is_enabled_defaults_to_true_when_missing(self):
        stream = self._build_stream([{"Number": 100, "EmailAddress": "x@y.com"}])
        records = list(stream.read_records(SyncMode.full_refresh))
        assert records[0]["is_enabled"] is True


# ----------------------------------------------------------------------
# Queue list caching — both queue-driven streams share one fetch
# ----------------------------------------------------------------------

class TestQueueListCache:
    def test_agents_stream_caches_queue_list_across_slices_and_reads(self):
        """`stream_slices` and `read_records` should share a single fetch
        of the queue list, not refetch it twice."""
        queue_rows = [
            {"Number": "8000", "Name": "Support"},
            {"Number": "8000", "Name": "Support"},  # dup → deduped
            {"Number": "8001", "Name": "Sales"},
        ]

        with patch("source_3cx_pbx_v20.streams.ThreeCXClient") as MockClient:
            instance = MockClient.return_value
            instance.list_queues.return_value = queue_rows
            instance.get_agents_in_queue_statistics.return_value = []

            stream = AgentsInQueueStatistics(CONFIG)
            slices = list(stream.stream_slices(SyncMode.full_refresh))

            # Drive read_records for every slice (which is what dbt-utils /
            # the Airbyte runtime would do)
            for sl in slices:
                list(stream.read_records(SyncMode.full_refresh, stream_slice=sl))

            # Only ONE call to list_queues, not 1+slices.
            assert instance.list_queues.call_count == 1
            # Two unique queues
            assert len(slices) == 2
            assert {s["queue_dn"] for s in slices} == {"8000", "8001"}


class TestAgentsStreamMonthlyEmission:
    """The connector must emit one record per (agent, queue, MONTH) so the
    dwh's monthly aggregation buckets correctly. Previously a single
    multi-month aggregate per (agent, queue) was being tagged with the
    lookback start, lumping everything into one month downstream."""

    def test_emits_one_record_per_month_per_agent(self):
        queue_rows = [{"Number": "8000", "Name": "Support"}]
        # The 3CX API would return this same shape for each per-month call.
        fake_agent = {
            "Dn": "100",
            "DnDisplayName": "Agent A",
            "AnsweredCount": 5,
        }

        with patch("source_3cx_pbx_v20.streams.ThreeCXClient") as MockClient:
            instance = MockClient.return_value
            instance.list_queues.return_value = queue_rows
            instance.get_agents_in_queue_statistics.return_value = [fake_agent]

            # lookback_months=2 → 3 months (2 ago + last + current)
            stream = AgentsInQueueStatistics({**CONFIG, "lookback_months": 2})
            slices = list(stream.stream_slices(SyncMode.full_refresh))
            records = []
            for sl in slices:
                records.extend(
                    stream.read_records(SyncMode.full_refresh, stream_slice=sl)
                )

            # 1 queue × 3 months × 1 mock agent
            assert len(records) == 3
            # Three distinct period_start values — proves the loop split
            assert len({r["period_start"] for r in records}) == 3
            # Every period_start is first-of-month
            assert all(r["period_start"].endswith("-01") for r in records)
            # API called once per month per queue
            assert instance.get_agents_in_queue_statistics.call_count == 3


# ----------------------------------------------------------------------
# Queues stream — record mapping + skip-on-missing-number
# ----------------------------------------------------------------------

class TestQueuesStream:
    def _build_stream(self, mock_queues):
        with patch("source_3cx_pbx_v20.streams.ThreeCXClient") as MockClient:
            instance = MockClient.return_value
            instance.list_queues.return_value = mock_queues
            return Queues(CONFIG)

    def test_emits_one_row_per_queue(self):
        stream = self._build_stream([
            {"Number": "8000", "Name": "Support"},
            {"Number": "8001", "Name": "Sales"},
        ])
        records = list(stream.read_records(SyncMode.full_refresh))
        assert [r["queue_dn"] for r in records] == ["8000", "8001"]
        assert records[0]["queue_display_name"] == "Support"

    def test_skips_queues_with_no_number(self):
        stream = self._build_stream([
            {"Number": None, "Name": "No DN"},
            {"Number": "8000", "Name": "Has DN"},
        ])
        records = list(stream.read_records(SyncMode.full_refresh))
        assert len(records) == 1
        assert records[0]["queue_dn"] == "8000"

    def test_stringifies_numeric_dn(self):
        """Number could come back as int — coerce to str to match
        the destination column type (varchar)."""
        stream = self._build_stream([{"Number": 8000, "Name": "Support"}])
        records = list(stream.read_records(SyncMode.full_refresh))
        assert records[0]["queue_dn"] == "8000"
