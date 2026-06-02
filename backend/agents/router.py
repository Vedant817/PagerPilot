import logging
from schema.evidence import PagerDutyIncident, Severity, Source
from backend.agents.base import BaseAgent, AgentResult
from backend.connectors import pagerduty
from backend.config import has_pagerduty, has_datadog, has_github, has_statusgator, external_deps_for_service

logger = logging.getLogger(__name__)


class RouterAgent(BaseAgent):
    name = "router"

    async def run(self, context: dict) -> AgentResult:
        incident_id = context.get("incident_id")
        if not incident_id:
            return AgentResult(False, error="incident_id is required")

        try:
            incident = await pagerduty.get_incident(incident_id)
        except Exception as e:
            logger.error(f"Failed to fetch PagerDuty incident {incident_id}: {e}")
            return AgentResult(False, error=f"Failed to fetch incident: {e}")

        if incident is None:
            return AgentResult(False, error=f"Incident {incident_id} not found")

        source_services = self._resolve_affected_services(incident)
        external_deps = self._resolve_external_dependencies(incident)

        context["incident"] = incident
        context["source_services"] = source_services
        context["external_dependencies"] = external_deps
        context["route"] = {
            "fetch_datadog": has_datadog(),
            "fetch_github": has_github(),
            "fetch_statusgator": has_statusgator(),
        }

        logger.info(
            f"RouterAgent: routed incident {incident_id} "
            f"to services {source_services}, deps {external_deps}"
        )

        return AgentResult(True, data={
            "incident_id": incident_id,
            "service": incident.service,
            "services_to_check": source_services,
            "external_deps": external_deps,
        })

    def _resolve_affected_services(self, incident: PagerDutyIncident) -> list[str]:
        return [incident.service]

    def _resolve_external_dependencies(self, incident: PagerDutyIncident) -> list[str]:
        return external_deps_for_service(incident.service)
