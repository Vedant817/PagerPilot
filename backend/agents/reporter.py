import logging
from datetime import datetime, timezone
from schema.evidence import (
    IncidentEvidence, IncidentBrief, RootCauseHypothesis, Source, ServiceImpact,
)
from backend.agents.base import BaseAgent, AgentResult
from backend.config import (
    dependency_graph_for_service, blast_radius_for_hypothesis,
)

logger = logging.getLogger(__name__)


def _build_recommended_action(
    evidence: IncidentEvidence,
    hypotheses: list[RootCauseHypothesis],
    context: dict,
) -> str:
    if not hypotheses:
        return "Insufficient evidence. Review service logs and metrics manually."

    top = hypotheses[0]
    title_lower = top.title.lower()
    actions = []
    service = evidence.incident.service

    deploy_keywords = ["deploy", "regression", "rollback", "rollout", "canary"]
    dependency_keywords = ["dependency", "third-party", "outage"]
    db_keywords = ["database", "capacity", "connection pool", "db"]

    if any(kw in title_lower for kw in deploy_keywords):
        actions = [
            f"1. Rollback the most recent deploy to {service}",
            "2. Verify error rates return to baseline after rollback",
            "3. Review changed files in the deploy for the root cause",
            "4. Notify the team via Slack #sre-review",
        ]
    elif any(kw in title_lower for kw in dependency_keywords):
        actions = [
            "1. Confirm third-party status page for ETA on resolution",
            "2. If available, fail over to secondary provider",
            "3. Update incident with external dependency reference",
            "4. Monitor for automatic recovery",
        ]
    elif any(kw in title_lower for kw in db_keywords):
        actions = [
            "1. Scale up database connection pool",
            "2. Identify and kill long-running queries",
            "3. Consider read replicas for query load",
            "4. Set up connection pool monitoring alert",
        ]
    else:
        actions = [
            f"1. Investigate {service} logs for error patterns",
            "2. Check recent configuration changes",
            "3. Review if traffic spike correlates with incident",
            "4. Engage on-call engineer for deep dive",
        ]

    recent_deploys = [e for e in evidence.github_events if e.type == "deploy"]
    status_outages = [s for s in evidence.status_events if s.incident]

    if recent_deploys:
        actions.append(
            f"5. Review deploy {recent_deploys[0].sha[:8] if recent_deploys[0].sha else 'details'}: "
            f"{recent_deploys[0].title}"
        )
    if status_outages:
        for outage in status_outages:
            actions.append(
                f"5. Check {outage.service} status: {outage.status}"
            )

    return "\n".join(actions[:6])


class ReporterAgent(BaseAgent):
    name = "reporter"

    async def run(self, context: dict) -> AgentResult:
        evidence: IncidentEvidence = context.get("evidence")
        hypotheses: list[RootCauseHypothesis] = context.get("hypotheses", [])

        if not evidence:
            return AgentResult(False, error="No evidence in context")

        brief = self._generate_brief(evidence, hypotheses, context)

        context["brief"] = brief

        logger.info(
            f"ReporterAgent: generated incident brief for {evidence.incident.id}"
        )

        return AgentResult(True, data={
            "brief": brief,
            "brief_id": f"brief-{evidence.incident.id}-{int(datetime.now(timezone.utc).timestamp())}",
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
        recommended_action = _build_recommended_action(
            evidence, hypotheses, context
        )
        service_impact = self._compute_service_impact(evidence, context)

        sources_used = set()
        if evidence.metrics or evidence.alerts:
            sources_used.add(Source.DATADOG)
        if evidence.github_events:
            sources_used.add(Source.GITHUB)
        if evidence.status_events:
            sources_used.add(Source.STATUSGATOR)
        sources_used.add(Source.PAGERDUTY)

        confidence = 0.5
        if top_hypothesis:
            confidence = top_hypothesis.confidence

        summary_parts = [
            f"Incident **{inc.id}** on **{inc.service}** "
            f"({inc.severity.value.upper()})",
            f"Status: {inc.status}",
            f"Generated at: {inc.created_at}",
        ]

        if hypotheses:
            top = hypotheses[0]
            summary_parts.append(f"**Top hypothesis (confidence {top.confidence:.0%}):** {top.title}")
            summary_parts.append(top.description[:200])

        if evidence.correlation_notes:
            summary_parts.append(f"**Signals:** {'; '.join(evidence.correlation_notes[:3])}")

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
            evidence_sources=list(sources_used),
            generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
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

        events.sort(key=lambda e: e["time"])
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
            if any(s.service == d for s in status_outages)
        ]

        hypotheses = context.get("hypotheses", [])
        blast_pct = 20
        if hypotheses:
            blast_pct = blast_radius_for_hypothesis(hypotheses[0].title)

        return ServiceImpact(
            affected_service=service,
            downstream_services=deps["downstream"],
            external_dependencies_impacted=impacted_external or external_deps,
            customer_facing=deps["customer_facing"],
            estimated_blast_percentage=blast_pct,
            affected_endpoints=deps["endpoints"],
        )
