import asyncio
import logging
from schema.evidence import (
    IncidentEvidence, Source, DatadogMetric, DatadogAlert,
    GitHubEvent, StatusGatorEvent,
)
from backend.agents.base import BaseAgent, AgentResult
from backend.connectors import datadog, github, statusgator

logger = logging.getLogger(__name__)


class SourceFetchAgent(BaseAgent):
    name = "source_fetch"

    async def run(self, context: dict) -> AgentResult:
        incident = context.get("incident")
        source_services = context.get("source_services", [])
        external_deps = context.get("external_dependencies", [])
        route = context.get("route", {})

        if not incident:
            return AgentResult(False, error="No incident in context")

        evidence = IncidentEvidence(incident=incident)
        errors: list[str] = []

        tasks = []

        if route.get("fetch_datadog"):
            for service in source_services:
                tasks.append(self._fetch_datadog_metrics(service, evidence, errors))
                tasks.append(self._fetch_datadog_alerts(service, evidence, errors))

        if route.get("fetch_github"):
            for service in source_services:
                tasks.append(self._fetch_github_deploys(service, evidence, errors))
                tasks.append(self._fetch_github_prs(service, evidence, errors))

        if route.get("fetch_statusgator"):
            for dep in external_deps:
                tasks.append(self._fetch_statusgator(dep, evidence, errors))

        if tasks:
            await asyncio.gather(*tasks)

        evidence.correlation_notes = self._generate_correlation_notes(evidence)

        context["evidence"] = evidence
        context["fetch_errors"] = errors

        logger.info(
            f"SourceFetchAgent: fetched {len(evidence.metrics)} metrics, "
            f"{len(evidence.alerts)} alerts, {len(evidence.github_events)} github events, "
            f"{len(evidence.status_events)} status events"
        )

        return AgentResult(True, data={
            "evidence": evidence,
            "errors": errors,
            "source_count": {
                "metrics": len(evidence.metrics),
                "alerts": len(evidence.alerts),
                "github": len(evidence.github_events),
                "status": len(evidence.status_events),
            },
        })

    async def _fetch_datadog_metrics(
        self, service: str, evidence: IncidentEvidence, errors: list[str],
    ):
        try:
            metrics = await datadog.get_service_metrics(service, "1h")
            evidence.metrics.extend(metrics)
        except Exception as e:
            errors.append(f"datadog:metrics:{service}: {e}")

    async def _fetch_datadog_alerts(
        self, service: str, evidence: IncidentEvidence, errors: list[str],
    ):
        try:
            alerts = await datadog.get_service_alerts(service)
            evidence.alerts.extend(alerts)
        except Exception as e:
            errors.append(f"datadog:alerts:{service}: {e}")

    async def _fetch_github_deploys(
        self, service: str, evidence: IncidentEvidence, errors: list[str],
    ):
        try:
            deploys = await github.get_recent_deploys(service, "24h")
            evidence.github_events.extend(deploys)
        except Exception as e:
            errors.append(f"github:deploys:{service}: {e}")

    async def _fetch_github_prs(
        self, service: str, evidence: IncidentEvidence, errors: list[str],
    ):
        try:
            prs = await github.get_prs_and_commits(service, "72h")
            evidence.github_events.extend(prs)
        except Exception as e:
            errors.append(f"github:prs:{service}: {e}")

    async def _fetch_statusgator(
        self, dep: str, evidence: IncidentEvidence, errors: list[str],
    ):
        try:
            status = await statusgator.get_service_status(dep)
            if status:
                evidence.status_events.append(status)
        except Exception as e:
            errors.append(f"statusgator:{dep}: {e}")

    def _generate_correlation_notes(self, evidence: IncidentEvidence) -> list[str]:
        notes = []

        if evidence.alerts:
            notes.append(f"{len(evidence.alerts)} active Datadog alerts for {evidence.incident.service}")

        if evidence.github_events:
            deploys = [e for e in evidence.github_events if e.type == "deploy"]
            if deploys:
                notes.append(f"Recent deploy at {deploys[0].timestamp}: {deploys[0].title}")

        if evidence.status_events:
            for se in evidence.status_events:
                if se.incident:
                    notes.append(f"Third-party outage detected: {se.service} - {se.status}")

        if evidence.metrics:
            anomalies = [m for m in evidence.metrics if m.anomaly]
            if anomalies:
                notes.append(f"{len(anomalies)} anomalous metrics detected")

        return notes
