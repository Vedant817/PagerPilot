import logging

from backend.agents.base import AgentResult, BaseAgent
from backend.config import external_deps_for_service, has_datadog, has_github, has_statusgator
from backend.connectors import pagerduty
from schema.evidence import PagerDutyIncident

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
            logger.error("Failed to fetch PagerDuty incident %s: %s", incident_id, e)
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
            "fetch_statusgator": bool(external_deps) and has_statusgator(),
        }

        logger.info(
            "RouterAgent: routed incident %s to services %s, deps %s",
            incident_id,
            source_services,
            external_deps,
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
