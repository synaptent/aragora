"""PagerDuty adapter for observability SLO alerts."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from aragora.connectors.devops.pagerduty import PagerDutyError

if TYPE_CHECKING:
    from aragora.observability.slo_alert_bridge import PagerDutyUrgency, SLOAlertConfig

logger = logging.getLogger(__name__)


class PagerDutySLOAlertSink:
    """Translate the observability sink contract to PagerDuty requests."""

    def __init__(self, config: SLOAlertConfig) -> None:
        self._config = config
        self._connector: Any | None = None
        self._owns_connector = False

    def _get_connector(self) -> Any:
        if self._connector is not None:
            return self._connector

        from aragora.connectors.devops.pagerduty import (
            PagerDutyConnector,
            PagerDutyCredentials,
        )

        credentials = PagerDutyCredentials(
            api_key=self._config.pagerduty_api_key or "",
            email=self._config.pagerduty_email,
        )
        self._connector = PagerDutyConnector(credentials)
        self._owns_connector = True
        return self._connector

    async def create_incident(
        self,
        *,
        title: str,
        service_id: str,
        urgency: PagerDutyUrgency,
        description: str,
        incident_key: str | None,
    ) -> str | None:
        """Create a PagerDuty incident and return its identifier."""
        try:
            from aragora.connectors.devops.pagerduty import (
                IncidentCreateRequest,
                IncidentUrgency,
            )

            request = IncidentCreateRequest(
                title=title,
                service_id=service_id,
                urgency=IncidentUrgency(urgency),
                description=description,
                incident_key=incident_key,
            )
            connector = self._get_connector()
            if self._owns_connector:
                async with connector as initialized:
                    incident = await initialized.create_incident(request)
            else:
                incident = await connector.create_incident(request)
            return incident.id
        except ImportError:
            logger.debug("PagerDuty connector not available")
            return None
        except (
            PagerDutyError,
            OSError,
            ConnectionError,
            TimeoutError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as e:
            logger.error("PagerDuty incident delivery failed: %s", e)
        return None

    async def resolve_incident(self, incident_id: str, resolution: str) -> bool:
        """Resolve a PagerDuty incident."""
        try:
            connector = self._get_connector()
            if self._owns_connector:
                async with connector as initialized:
                    await initialized.resolve_incident(
                        incident_id,
                        resolution=resolution,
                    )
            else:
                await connector.resolve_incident(
                    incident_id,
                    resolution=resolution,
                )
            return True
        except ImportError:
            logger.debug("PagerDuty connector not available")
            return False
        except (
            PagerDutyError,
            OSError,
            ConnectionError,
            TimeoutError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as e:
            logger.error("PagerDuty incident resolution failed: %s", e)
            return False


def register_slo_alert_sink() -> bool:
    """Register this adapter with the observability-owned sink contract."""
    try:
        from aragora.observability.slo_alert_bridge import register_pagerduty_alert_sink
    except ImportError as e:
        logger.debug("Observability PagerDuty sink contract unavailable: %s", e)
        return False

    register_pagerduty_alert_sink(PagerDutySLOAlertSink)
    return True


__all__ = ["PagerDutySLOAlertSink", "register_slo_alert_sink"]
