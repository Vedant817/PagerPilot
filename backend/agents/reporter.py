import logging

from backend.agents.base import AgentResult, BaseAgent
from backend.config import blast_radius_for_hypothesis, dependency_graph_for_service
from backend.timeutils import timestamp_sort_key, utc_now_iso
from schema.evidence import IncidentBrief, IncidentEvidence, RootCauseHypothesis, ServiceImpact, Source

logger = logging.getLogger(__name__)


def _build_recommended_action(
    evidence: IncidentEvidence,
    hypotheses: list[RootCauseHypothesis],
    context: dict,
) -> str:
    if not hypotheses:
        return "1. Insufficient evidence. Review service logs and metrics manually."

    top = hypotheses[0]
    title_lower = top.title.lower()
    service = evidence.incident.service

    deploy_keywords = ["deploy", "regression", "rollback", "rollout", "canary"]
    dependency_keywords = ["dependency", "third-party", "outage"]
    db_keywords = ["database", "capacity", "connection pool", "db"]

    if any(kw in title_lower for kw in deploy_keywords):
        actions = [
            f"Rollback or pause the most recent deploy to {service}",
            "Verify error rates and latency return to baseline after mitigation",
            "Review changed files in the deploy for the exact regression",
            "Notify the incident channel with the suspected deploy SHA and owner",
        ]
    elif any(kw in title_lower for kw in dependency_keywords):
        actions = [
            "Confirm the third-party status page and capture incident reference/ETA",
            "Fail over to a secondary provider or degraded mode if available",
            "Update the customer-facing incident with the external dependency reference",
            "Monitor dependency recovery and retry backlog drain",
        ]
    elif any(kw in title_lower for kw in db_keywords):
        actions = [
            "Scale database connection capacity or reduce pool pressure immediately",
            "Identify long-running queries and high-cardinality callers",
            "Temporarily shed non-critical traffic or background jobs if queues grow",
            "Add or tune connection pool saturation alerts after mitigation",
        ]
    else:
        actions = [
            f"Investigate {service} logs for repeated error signatures",
            "Check recent configuration and feature-flag changes",
            "Review traffic spikes and dependency latency during the incident window",
            "Engage the owning on-call engineer for service-specific triage",
        ]

    recent_deploys = [e for e in evidence.github_events if e.type == "deploy"]
    status_outages = [s for s in evidence.status_events if s.incident]

    if recent_deploys:
        deploy = recent_deploys[0]
        sha = deploy.sha[:8] if deploy.sha else "unknown-sha"
        actions.append(f"Review deploy {sha}: {deploy.title}")
    for outage in status_outages:
        actions.append(f"Track {outage.service} status until it returns to operational")

    return "\n".join(f"{idx}. {action}" for idx, action in enumerate(actions[:6], start=1))


class ReporterAgent(BaseAgent):
    name = "reporter"

    async def run(self, context: dict) -> AgentResult:
        evidence: IncidentEvidence = context.get("evidence")
        hypotheses: list[RootCauseHypothesis] = context.get("hypotheses", [])

        if not evidence:
            return AgentResult(False, error="No evidence in context")

        brief = self._generate_brief(evidence, hypotheses, context)

        context["brief"] = brief

        logger.info("ReporterAgent: generated incident brief for %s", evidence.incident.id)

        return AgentResult(True, data={
            "brief": brief,
            "brief_id": f"brief-{evidence.incident.id}-{utc_now_iso()}",
        })

    def _generate_brief(
        self,
        evidence: IncidentEvidence,
        hypotheses: list[RootCauseHypothesis],
        context: dict,
    ) -> IncidentBrief:
        inc = evidence.incident
        timeline = self._build_timeline(evidence)

        top_hypothesis = hypotheses[0] if hypotheses else None
        recommended_action = _build_recommended_action(evidence, hypotheses, context)
        service_impact = self._compute_service_impact(evidence, context)

        sources_used = {Source.PAGERDUTY}
        if evidence.metrics or evidence.alerts:
            sources_used.add(Source.DATADOG)
        if evidence.github_events:
            sources_used.add(Source.GITHUB)
        if evidence.status_events:
            sources_used.add(Source.STATUSGATOR)
        source_order = [Source.PAGERDUTY, Source.DATADOG, Source.GITHUB, Source.STATUSGATOR]

        confidence = top_hypothesis.confidence if top_hypothesis else 0.5
        generated_at = utc_now_iso()

        summary_parts = [
            f"Incident **{inc.id}** on **{inc.service}** ({inc.severity.value.upper()})",
            f"Status: {inc.status}",
            f"Triggered at: {inc.created_at}",
            f"Brief generated at: {generated_at}",
        ]

        if hypotheses:
            top = hypotheses[0]
            summary_parts.append(f"**Top hypothesis (confidence {top.confidence:.0%}):** {top.title}")
            summary_parts.append(top.description[:240])

        if evidence.correlation_notes:
            summary_parts.append(f"**Signals:** {'; '.join(evidence.correlation_notes[:3])}")

        fetch_errors = context.get("fetch_errors", [])
        if fetch_errors:
            summary_parts.append(f"**Caveat:** {len(fetch_errors)} source call(s) failed; confidence may be lower.")

        return IncidentBrief(
            incident_id=inc.id,
            title=inc.title,
            service=inc.service,
            severity=inc.severity,
            status=inc.status,
            summary="\n\n".join(summary_parts),
            timeline=timeline,
            root_cause_hypotheses=hypotheses,
            recommended_action=recommended_action,
            evidence_sources=[s for s in source_order if s in sources_used],
            generated_at=generated_at,
            confidence_score=confidence,
            service_impact=service_impact,
        )

    def _build_timeline(self, evidence: IncidentEvidence) -> list[dict]:
        events = []

        events.append({
            "time": evidence.incident.created_at,
            "source": "pagerduty",
            "event": f"Incident triggered: {evidence.incident.title}",
        })

        for alert in evidence.alerts:
            events.append({
                "time": alert.triggered_at,
                "source": "datadog",
                "event": f"Alert triggered: {alert.title} (value: {alert.value})",
            })

        for gh in evidence.github_events:
            events.append({
                "time": gh.timestamp,
                "source": "github",
                "event": f"{gh.type.upper()}: {gh.title} by {gh.author}",
            })

        for se in evidence.status_events:
            events.append({
                "time": se.last_updated,
                "source": "statusgator",
                "event": f"Status: {se.service} - {se.status}",
            })

        events.sort(key=lambda e: timestamp_sort_key(e.get("time")))
        return events

    def _compute_service_impact(
        self,
        evidence: IncidentEvidence,
        context: dict,
    ) -> ServiceImpact:
        service = evidence.incident.service
        deps = dependency_graph_for_service(service)

        external_deps = context.get("external_dependencies", [])
        status_outages = [s for s in evidence.status_events if s.incident]
        impacted_external = [
            d for d in external_deps
            if any(s.service.lower() == d.lower() for s in status_outages)
        ]

        hypotheses = context.get("hypotheses", [])
        blast_pct = 20
        if hypotheses:
            blast_pct = blast_radius_for_hypothesis(hypotheses[0].title)

        return ServiceImpact(
            affected_service=service,
            downstream_services=deps.get("downstream", []),
            external_dependencies_impacted=impacted_external,
            customer_facing=bool(deps.get("customer_facing", True)),
            estimated_blast_percentage=blast_pct,
            affected_endpoints=deps.get("endpoints", []),
        )
