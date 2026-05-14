"""3CX XAPI client for the Airbyte connector.

Handles OAuth2 authentication, pagination, and all working endpoints:

- ``CallLogData`` — per-call records (incremental, chunked)
- ``QueuePerformanceOverview`` — per-extension queue stats (full refresh)
- ``AgentsInQueueStatistics`` — per-agent queue stats (full refresh, per-queue)
- ``Users`` — extension / user master (full refresh, paginated)

All operations are READ-ONLY against the 3CX Management API.
"""

import logging
import re
import time
from datetime import datetime, timezone

import requests

log = logging.getLogger(__name__)

# Default HTTP timeout for all calls. 3CX endpoints normally answer in <5s
# but report endpoints can be slow on large windows.
DEFAULT_TIMEOUT_SECONDS = 60


def parse_iso_duration(s):
    """Convert ISO 8601 duration (e.g. ``PT3M12.139836S``, ``P1DT2H``) to
    integer seconds.

    Accepts the full pattern 3CX's XAPI emits per its OpenAPI spec:
    ``^-?P([0-9]+D)?(T([0-9]+H)?([0-9]+M)?([0-9]+([.][0-9]+)?S)?)?$``.
    Notably this includes the days component, which the prior regex
    silently zeroed — call durations >24h, multi-day shift aggregates,
    and large queue talk-time rollups all need it.

    Returns 0 if the string is None, empty, or unparseable.
    """
    if not s:
        return 0
    m = re.match(
        r"^(-)?P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?)?$",
        s,
        re.IGNORECASE,
    )
    if not m:
        return 0
    sign = -1 if m.group(1) else 1
    days = int(m.group(2) or 0)
    hours = int(m.group(3) or 0)
    minutes = int(m.group(4) or 0)
    seconds = float(m.group(5) or 0)
    return sign * int(days * 86400 + hours * 3600 + minutes * 60 + seconds)


def _odata_datetime(dt):
    """Format a datetime as ISO 8601 with Z suffix for OData parameters."""
    if isinstance(dt, str):
        return dt
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class ThreeCXClient:
    """Client for the 3CX XAPI (read-only)."""

    PAGE_SIZE = 1000
    # /xapi/v1/Users rejects `$top` values above ~100 with a 400 Bad
    # Request — server-side OData validation, not a connector concern.
    # 100 matches 3CX's own admin tooling default and is the largest
    # value we've observed accepted in the wild.
    USERS_PAGE_SIZE = 100
    MAX_RETRIES = 3
    RETRY_BACKOFF = 5  # seconds

    def __init__(
        self,
        fqdn: str,
        client_id: str,
        client_secret: str,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ):
        self.base_url = f"https://{fqdn}"
        self.client_id = client_id
        self.client_secret = client_secret
        self._timeout = timeout
        self._token = None
        self._token_expires_at = 0
        self.session = requests.Session()

    def _authenticate(self):
        """Obtain or refresh OAuth2 access token."""
        if self._token and time.time() < self._token_expires_at - 30:
            return
        log.info("Authenticating with 3CX at %s", self.base_url)
        self.session.headers.pop("Authorization", None)
        resp = self.session.post(
            f"{self.base_url}/connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict) or "access_token" not in data:
            raise RuntimeError(
                f"3CX OAuth response did not contain access_token: {data!r}"
            )
        self._token = data["access_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 3600)
        self.session.headers["Authorization"] = f"Bearer {self._token}"

    def _get(self, url: str, params: dict = None) -> dict:
        """GET with auth, 429 backoff, and 401 re-auth.

        Returns the parsed JSON body. Raises if the response is malformed,
        if all retries are exhausted, or if the server returns an error
        status that isn't 401/429.
        """
        self._authenticate()
        for attempt in range(1, self.MAX_RETRIES + 1):
            resp = self.session.get(url, params=params, timeout=self._timeout)
            if resp.status_code == 401:
                log.warning(
                    "Got 401, re-authenticating (attempt %d/%d)",
                    attempt, self.MAX_RETRIES,
                )
                self._token = None
                self._authenticate()
                continue
            if resp.status_code == 429:
                wait = self.RETRY_BACKOFF * attempt
                log.warning(
                    "Rate limited (429), waiting %ds (attempt %d/%d)",
                    wait, attempt, self.MAX_RETRIES,
                )
                time.sleep(wait)
                continue
            resp.raise_for_status()
            try:
                data = resp.json()
            except ValueError as exc:
                raise RuntimeError(
                    f"3CX returned non-JSON response for {url}: {exc}"
                ) from exc
            if not isinstance(data, dict):
                raise RuntimeError(
                    f"3CX response body was not a JSON object for {url}: "
                    f"got {type(data).__name__}"
                )
            return data
        # All retries exhausted — surface the last status.
        resp.raise_for_status()

    def _get_collection(self, url: str, params: dict = None) -> list[dict]:
        """GET an OData collection and return its ``value`` array.

        Returns an empty list if the field is absent. Raises if the field
        is present but isn't a list.
        """
        data = self._get(url, params=params)
        records = data.get("value", [])
        if not isinstance(records, list):
            raise RuntimeError(
                f"3CX OData response 'value' was not a list for {url}: "
                f"got {type(records).__name__}"
            )
        return records

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    def check_connection(self) -> tuple[bool, str]:
        """Verify credentials and connectivity by fetching 1 record."""
        try:
            self._authenticate()
            now = datetime.now(timezone.utc)
            path = (
                f"/xapi/v1/ReportCallLogData/Pbx.GetCallLogData("
                f"periodFrom={_odata_datetime(now)},"
                f"periodTo={_odata_datetime(now)},"
                f"sourceType=0,sourceFilter='',"
                f"destinationType=0,destinationFilter='',"
                f"callsType=0,callTimeFilterType=0,"
                f"callTimeFilterFrom='0:00:0',callTimeFilterTo='0:00:0',"
                f"hidePcalls=false)"
            )
            self._get(f"{self.base_url}{path}", params={"$top": 1, "$skip": 0})
            return True, ""
        except Exception as exc:
            return False, str(exc)

    # ------------------------------------------------------------------
    # Streams
    # ------------------------------------------------------------------

    def get_call_log_data(self, period_from, period_to) -> list[dict]:
        """Fetch all call log records for the given period, paginating automatically."""
        all_records: list[dict] = []
        skip = 0
        base_path = (
            f"/xapi/v1/ReportCallLogData/Pbx.GetCallLogData("
            f"periodFrom={_odata_datetime(period_from)},"
            f"periodTo={_odata_datetime(period_to)},"
            f"sourceType=0,sourceFilter='',"
            f"destinationType=0,destinationFilter='',"
            f"callsType=0,callTimeFilterType=0,"
            f"callTimeFilterFrom='0:00:0',callTimeFilterTo='0:00:0',"
            f"hidePcalls=false)"
        )
        while True:
            url = f"{self.base_url}{base_path}"
            records = self._get_collection(
                url, params={"$top": self.PAGE_SIZE, "$skip": skip}
            )
            if not records:
                break
            all_records.extend(records)
            log.info(
                "CallLogData: fetched %d records (total: %d)",
                len(records), len(all_records),
            )
            if len(records) < self.PAGE_SIZE:
                break
            skip += self.PAGE_SIZE
        return all_records

    def list_queues(self) -> list[dict]:
        """List queue entities from `/xapi/v1/Queues`.

        Returns one row per queue with ``Number`` (the queue DN) and
        ``Name`` (display name). Used to slice
        ``AgentsInQueueStatistics`` by queue.

        We deliberately don't paginate here — a single PBX rarely has
        more than a few dozen queues, and the OData `$top` default
        sits comfortably above that. If an install ever has more than
        200 queues, raise the cap or add pagination.
        """
        path = "/xapi/v1/Queues"
        records = self._get_collection(
            f"{self.base_url}{path}",
            params={"$top": 200, "$select": "Number,Name"},
        )
        log.info("Queues: fetched %d records", len(records))
        return records

    def get_agents_in_queue_statistics(
        self, queue_dn: str, period_from, period_to,
    ) -> list[dict]:
        """Fetch per-agent statistics for a specific queue."""
        path = (
            f"/xapi/v1/ReportAgentsInQueueStatistics/Pbx.GetAgentsInQueueStatisticsData("
            f"queueDnStr='{queue_dn}',"
            f"startDt={_odata_datetime(period_from)},"
            f"endDt={_odata_datetime(period_to)},"
            f"waitInterval='0:00:0')"
        )
        records = self._get_collection(f"{self.base_url}{path}")
        log.info(
            "AgentsInQueueStatistics (queue=%s): fetched %d records",
            queue_dn, len(records),
        )
        return records

    def get_users(self) -> list[dict]:
        """Fetch the full 3CX user / extension master.

        Standard OData collection at ``/xapi/v1/Users`` with $top/$skip
        pagination. Uses ``USERS_PAGE_SIZE`` (default 100) because that
        endpoint enforces a smaller $top cap than the rest of the API
        — passing 1000 returns a 400 Bad Request.
        """
        all_records: list[dict] = []
        skip = 0
        path = "/xapi/v1/Users"
        while True:
            url = f"{self.base_url}{path}"
            records = self._get_collection(
                url, params={"$top": self.USERS_PAGE_SIZE, "$skip": skip}
            )
            if not records:
                break
            all_records.extend(records)
            log.info(
                "Users: fetched %d records (total: %d)",
                len(records), len(all_records),
            )
            if len(records) < self.USERS_PAGE_SIZE:
                break
            skip += self.USERS_PAGE_SIZE
        return all_records
