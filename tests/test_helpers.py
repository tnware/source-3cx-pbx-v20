"""Tests for pure helper functions — no HTTP, no I/O."""

import pytest

from source_3cx_pbx_v20.client import parse_iso_duration, _odata_datetime
from source_3cx_pbx_v20.streams import (
    _parse_iso_datetime,
    _start_of_month_n_ago,
    _period_from_config,
)
from datetime import datetime, timezone, date


# ----------------------------------------------------------------------
# parse_iso_duration
# ----------------------------------------------------------------------

class TestParseIsoDuration:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("PT3M12.139836S", 192),
            ("PT5S", 5),
            ("PT1H", 3600),
            ("PT1H30M", 5400),
            ("PT2H15M30S", 8130),
            ("PT0S", 0),
        ],
    )
    def test_parses_valid_durations(self, value, expected):
        assert parse_iso_duration(value) == expected

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("P1D", 86_400),
            ("P2D", 172_800),
            ("P1DT2H", 86_400 + 7200),
            ("P1DT2H30M", 86_400 + 7200 + 1800),
            ("P1DT2H30M15S", 86_400 + 7200 + 1800 + 15),
            # Days-only with no time component still parses cleanly.
            ("P7D", 604_800),
        ],
    )
    def test_parses_durations_with_day_component(self, value, expected):
        """3CX's spec allows P([0-9]+D)?T... — calls >24h, shift
        aggregates, and large queue rollups all rely on this."""
        assert parse_iso_duration(value) == expected

    def test_accepts_negative_sign(self):
        """The spec regex includes an optional leading ``-``. Unlikely
        in practice but parse it rather than silently zero."""
        assert parse_iso_duration("-PT5S") == -5

    @pytest.mark.parametrize("value", [None, "", "garbage", "PT", "3 minutes"])
    def test_returns_zero_for_invalid(self, value):
        assert parse_iso_duration(value) == 0


# ----------------------------------------------------------------------
# _odata_datetime
# ----------------------------------------------------------------------

def test_odata_datetime_passthrough_for_string():
    assert _odata_datetime("2026-01-15T09:00:00Z") == "2026-01-15T09:00:00Z"


def test_odata_datetime_formats_datetime():
    dt = datetime(2026, 1, 15, 9, 0, 0, tzinfo=timezone.utc)
    assert _odata_datetime(dt) == "2026-01-15T09:00:00Z"


# ----------------------------------------------------------------------
# _parse_iso_datetime
# ----------------------------------------------------------------------

class TestParseIsoDatetime:
    def test_parses_z_suffix(self):
        out = _parse_iso_datetime("2026-01-15T09:00:00Z")
        assert out == datetime(2026, 1, 15, 9, 0, 0, tzinfo=timezone.utc)

    def test_parses_offset_suffix(self):
        out = _parse_iso_datetime("2026-01-15T09:00:00+00:00")
        assert out == datetime(2026, 1, 15, 9, 0, 0, tzinfo=timezone.utc)

    @pytest.mark.parametrize("value", [None, "", "not-a-date", "2026/01/15"])
    def test_returns_none_for_unparseable(self, value):
        assert _parse_iso_datetime(value) is None


# ----------------------------------------------------------------------
# _start_of_month_n_ago — boundary behavior
# ----------------------------------------------------------------------

class TestStartOfMonthNAgo:
    def test_zero_returns_current_month_start(self, monkeypatch):
        """N=0 should return the 1st of the current month."""
        # Freeze "today" by monkeypatching the date class.
        import source_3cx_pbx_v20.streams as streams_mod

        class FixedDate(date):
            @classmethod
            def today(cls):
                return date(2026, 5, 15)

        monkeypatch.setattr(streams_mod, "date", FixedDate)
        assert _start_of_month_n_ago(0) == date(2026, 5, 1)

    def test_crosses_year_boundary(self, monkeypatch):
        import source_3cx_pbx_v20.streams as streams_mod

        class FixedDate(date):
            @classmethod
            def today(cls):
                return date(2026, 2, 15)

        monkeypatch.setattr(streams_mod, "date", FixedDate)
        # 3 months before Feb 2026 = Nov 2025
        assert _start_of_month_n_ago(3) == date(2025, 11, 1)


# ----------------------------------------------------------------------
# _period_from_config — uses lookback_months
# ----------------------------------------------------------------------

def test_period_from_config_respects_lookback():
    period_from, period_to = _period_from_config({"lookback_months": 1})
    assert period_from < period_to
    # period_from should be on the 1st of some month
    assert period_from.day == 1
