"""Tests for the 3CX streams — mock the ThreeCXClient where needed."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from airbyte_cdk.models import SyncMode

from source_3cx_pbx_v20.streams import (
    CallLogData,
    QueuePerformanceOverview,
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
            {"QueueDn": "8000", "QueueDisplayName": "Support"},
            {"QueueDn": "8000", "QueueDisplayName": "Support"},  # dup → deduped
            {"QueueDn": "8001", "QueueDisplayName": "Sales"},
        ]

        with patch("source_3cx_pbx_v20.streams.ThreeCXClient") as MockClient:
            instance = MockClient.return_value
            instance.get_queue_performance_overview.return_value = queue_rows
            instance.get_agents_in_queue_statistics.return_value = []

            stream = AgentsInQueueStatistics(CONFIG)
            slices = list(stream.stream_slices(SyncMode.full_refresh))

            # Drive read_records for every slice (which is what dbt-utils /
            # the Airbyte runtime would do)
            for sl in slices:
                list(stream.read_records(SyncMode.full_refresh, stream_slice=sl))

            # Only ONE call to get_queue_performance_overview, not 1+slices.
            assert instance.get_queue_performance_overview.call_count == 1
            # Two unique queues
            assert len(slices) == 2
            assert {s["queue_dn"] for s in slices} == {"8000", "8001"}
