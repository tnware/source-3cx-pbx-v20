"""Tests for ThreeCXClient — HTTP behavior via the `responses` mock library."""

import json

import pytest
import responses

from source_3cx_pbx_v20.client import ThreeCXClient


@pytest.fixture
def client():
    """Fresh client with deterministic config for each test."""
    return ThreeCXClient(
        fqdn="pbx.example.com",
        client_id="cid",
        client_secret="csecret",
        timeout=5,
    )


def _stub_token(success=True):
    """Register the token endpoint with a successful response by default."""
    body = (
        {"access_token": "tok", "expires_in": 3600}
        if success
        else {"error": "invalid_client"}
    )
    responses.add(
        responses.POST,
        "https://pbx.example.com/connect/token",
        json=body,
        status=200 if success else 400,
    )


# ----------------------------------------------------------------------
# Authentication
# ----------------------------------------------------------------------

class TestAuthentication:
    @responses.activate
    def test_authenticate_sets_bearer_token(self, client):
        _stub_token()
        client._authenticate()
        assert client._token == "tok"
        assert client.session.headers["Authorization"] == "Bearer tok"

    @responses.activate
    def test_authenticate_raises_on_missing_access_token(self, client):
        responses.add(
            responses.POST,
            "https://pbx.example.com/connect/token",
            json={"not_a_token": "oops"},
            status=200,
        )
        with pytest.raises(RuntimeError, match="access_token"):
            client._authenticate()


# ----------------------------------------------------------------------
# _get error paths
# ----------------------------------------------------------------------

class TestGet:
    @responses.activate
    def test_returns_parsed_json_on_success(self, client):
        _stub_token()
        responses.add(
            responses.GET,
            "https://pbx.example.com/x",
            json={"value": [{"a": 1}]},
            status=200,
        )
        out = client._get("https://pbx.example.com/x")
        assert out == {"value": [{"a": 1}]}

    @responses.activate
    def test_401_reauths_and_retries(self, client):
        # token call happens twice (initial + after 401)
        _stub_token()
        _stub_token()
        responses.add(
            responses.GET,
            "https://pbx.example.com/x",
            json={"error": "expired"},
            status=401,
        )
        responses.add(
            responses.GET,
            "https://pbx.example.com/x",
            json={"value": []},
            status=200,
        )
        out = client._get("https://pbx.example.com/x")
        assert out == {"value": []}

    @responses.activate
    def test_429_backs_off_and_retries(self, client, monkeypatch):
        # Don't actually sleep during the test.
        import source_3cx_pbx_v20.client as client_mod
        monkeypatch.setattr(client_mod.time, "sleep", lambda *_: None)

        _stub_token()
        responses.add(
            responses.GET,
            "https://pbx.example.com/x",
            json={"rate_limited": True},
            status=429,
        )
        responses.add(
            responses.GET,
            "https://pbx.example.com/x",
            json={"value": [{"ok": True}]},
            status=200,
        )
        out = client._get("https://pbx.example.com/x")
        assert out == {"value": [{"ok": True}]}

    @responses.activate
    def test_raises_on_non_dict_body(self, client):
        _stub_token()
        responses.add(
            responses.GET,
            "https://pbx.example.com/x",
            json=["a", "list", "not", "a", "dict"],
            status=200,
        )
        with pytest.raises(RuntimeError, match="not a JSON object"):
            client._get("https://pbx.example.com/x")

    @responses.activate
    def test_raises_on_non_json_body(self, client):
        _stub_token()
        responses.add(
            responses.GET,
            "https://pbx.example.com/x",
            body="<html>500</html>",
            status=200,
            content_type="text/html",
        )
        with pytest.raises(RuntimeError, match="non-JSON response"):
            client._get("https://pbx.example.com/x")


# ----------------------------------------------------------------------
# _get_collection
# ----------------------------------------------------------------------

class TestGetCollection:
    @responses.activate
    def test_returns_value_list(self, client):
        _stub_token()
        responses.add(
            responses.GET,
            "https://pbx.example.com/x",
            json={"value": [{"a": 1}, {"a": 2}]},
            status=200,
        )
        assert client._get_collection("https://pbx.example.com/x") == [
            {"a": 1}, {"a": 2},
        ]

    @responses.activate
    def test_returns_empty_when_value_missing(self, client):
        _stub_token()
        responses.add(
            responses.GET,
            "https://pbx.example.com/x",
            json={"some_other_key": []},
            status=200,
        )
        assert client._get_collection("https://pbx.example.com/x") == []

    @responses.activate
    def test_raises_when_value_is_not_a_list(self, client):
        _stub_token()
        responses.add(
            responses.GET,
            "https://pbx.example.com/x",
            json={"value": "should be a list"},
            status=200,
        )
        with pytest.raises(RuntimeError, match="not a list"):
            client._get_collection("https://pbx.example.com/x")


# ----------------------------------------------------------------------
# Users pagination
# ----------------------------------------------------------------------

class TestGetUsers:
    @responses.activate
    def test_single_page(self, client):
        _stub_token()
        responses.add(
            responses.GET,
            "https://pbx.example.com/xapi/v1/Users",
            json={"value": [
                {"Number": "100", "EmailAddress": "a@x.com"},
                {"Number": "101", "EmailAddress": "b@x.com"},
            ]},
            status=200,
        )
        users = client.get_users()
        assert len(users) == 2
        assert users[0]["Number"] == "100"

    @responses.activate
    def test_paginates_until_short_page(self, client, monkeypatch):
        # Override the Users page-size constant so we don't need 100
        # mock records to exercise the loop.
        monkeypatch.setattr(ThreeCXClient, "USERS_PAGE_SIZE", 2)

        _stub_token()
        responses.add(
            responses.GET,
            "https://pbx.example.com/xapi/v1/Users",
            json={"value": [{"Number": "100"}, {"Number": "101"}]},
            status=200,
        )
        responses.add(
            responses.GET,
            "https://pbx.example.com/xapi/v1/Users",
            json={"value": [{"Number": "102"}]},   # short page → loop exits
            status=200,
        )
        users = client.get_users()
        assert [u["Number"] for u in users] == ["100", "101", "102"]
