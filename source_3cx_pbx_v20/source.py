"""AbstractSource implementation for the 3CX XAPI connector."""

import logging
from typing import Any, List, Mapping, Tuple

from airbyte_cdk.sources import AbstractSource
from airbyte_cdk.sources.streams import Stream

from .client import ThreeCXClient
from .streams import (
    AgentsInQueueStatistics,
    CallLogData,
    QueuePerformanceOverview,
    Users,
)

log = logging.getLogger(__name__)


class Source3cxPbxV20(AbstractSource):
    """Airbyte source connector for the 3CX PBX XAPI."""

    def check_connection(self, logger, config: Mapping[str, Any]) -> Tuple[bool, Any]:
        client = ThreeCXClient(
            fqdn=config["fqdn"],
            client_id=config["client_id"],
            client_secret=config["client_secret"],
        )
        ok, error = client.check_connection()
        return ok, error if not ok else None

    def streams(self, config: Mapping[str, Any]) -> List[Stream]:
        return [
            CallLogData(config),
            QueuePerformanceOverview(config),
            AgentsInQueueStatistics(config),
            Users(config),
        ]
