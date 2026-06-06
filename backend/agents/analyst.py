import logging

from backend.agents.base import AgentResult, BaseAgent
from backend.config import analysis_rules_for_service
from backend.timeutils import parse_timestamp
from schema.evidence import IncidentEvidence, RootCauseHypothesis, Source

logger = logging.getLogger(__name__)


def _compute_confidence(signal_count: int, alert_count: int, anomaly_count: int, has_deploy: bool) -> float:
    base = 0.2
    if has_deploy:
        base += 0.15
    base += min(signal_count * 0.1, 0.3)
    if alert_count > 0:
        base += min(alert_count * 0.05, 0.15)
    if anomaly_count > 0:
        base += min(anomaly_count * 0.08, 0.2)
    return round(min(base, 0.95), 2)


def _matches_rule(text: str, rule_keywords: list[str]) -> bool:
    text_lower = (text or "").lower()
    return any(kw.lower() in text_lower for kw in rule_keywords)


def _unique_sources(*sources: Source | None) -> list[Source]:
    ordered: list[Source] = []
    for source in sources:
        if source and source not in ordered:
            ordered.append(source)
    return ordered


class AnalystAgent(BaseAgent):
    name = "analyst"

    async def run(self, context: dict) -> AgentResult:
        evidence: IncidentEvidence = context.get("evidence")
        if not evidence:
            return AgentResult(False, error="No evidence in context")

        hypotheses = self._rank_hypotheses(evidence)
        correlation_notes = self._correlate_signals(evidence)

        evidence.correlation_notes.extend(correlation_notes)

        hypotheses.sort(key=lambda h: h.confidence, reverse=True)
        for i, h in enumerate(hypotheses):
            h.rank = i + 1

        context["hypotheses"] = hypotheses
        context["correlation_notes"] = correlation_notes

        logger.info("AnalystAgent: generated %s ranked hypotheses", len(hypotheses))

        return AgentResult(True, data={
            "hypotheses": hypotheses,
            "hypothesis_count": len(hypotheses),
            "top_hypothesis": hypotheses[0].title if hypotheses else None,
        })

    def _rank_hypotheses(self, evidence: IncidentEvidence) -> list[RootCauseHypothesis]:
        hypotheses: list[RootCauseHypothesis] = []
        service = evidence.incident.service
        incident_text = " ".join([
            evidence.incident.title or "",
            evidence.incident.description or "",
            evidence.incident.status or "",
        ])

        recent_deploys = [e for e in evidence.github_events if e.type == "deploy"]
        has_recent_deploy = bool(recent_deploys)

        status_outages = [s for s in evidence.status_events if s.incident]
        has_external_outage = bool(status_outages)

        anomalies = [m for m in evidence.metrics if m.anomaly]
        alerts = evidence.alerts
        rules = analysis_rules_for_service(service)

        error_keywords = rules.get("error_keywords", ["error", "fault", "exception", "fail"])
        latency_keywords = rules.get("latency_keywords", ["latency", "p99", "p95", "response_time"])
        db_keywords = rules.get("db_keywords", ["db.connections", "database", "connection_pool", "pg_stat"])
        deploy_keywords = rules.get("deploy_keywords", ["deploy", "health", "canary", "rollout"])

        alert_text = " ".join([f"{a.title} {a.query}" for a in alerts])

        has_error_spike = any(
            _matches_rule(m.metric_name, error_keywords) and m.anomaly
            for m in evidence.metrics
        ) or _matches_rule(alert_text, error_keywords) or _matches_rule(incident_text, error_keywords)

        has_latency_spike = any(
            _matches_rule(m.metric_name, latency_keywords) and m.anomaly
            for m in evidence.metrics
        ) or _matches_rule(alert_text, latency_keywords) or _matches_rule(incident_text, latency_keywords)

        db_anomalies = [
            m for m in anomalies
            if _matches_rule(m.metric_name, db_keywords)
        ]
        has_db_pressure = bool(db_anomalies) or _matches_rule(alert_text, db_keywords) or _matches_rule(incident_text, db_keywords)

        deploy_event_keywords = [kw for kw in deploy_keywords if kw.lower() != "health"]
        incident_mentions_deploy = _matches_rule(incident_text, deploy_event_keywords)
        has_deploy_failure = any(
            _matches_rule(m.metric_name, deploy_keywords) and m.anomaly
            for m in evidence.metrics
        ) or _matches_rule(alert_text, deploy_keywords) or (
            incident_mentions_deploy and _matches_rule(incident_text, deploy_keywords)
        )

        if (has_recent_deploy or incident_mentions_deploy) and (
            has_error_spike or has_latency_spike or has_deploy_failure
        ):
            deploy = recent_deploys[0] if recent_deploys else None
            confidence = _compute_confidence(
                signal_count=len(evidence.github_events) + len(evidence.metrics) + 1,
                alert_count=len(alerts),
                anomaly_count=len(anomalies),
                has_deploy=has_recent_deploy or incident_mentions_deploy,
            )
            evidence_items = []
            if deploy:
                evidence_items.append(f"Deploy at {deploy.timestamp}: {deploy.title}")
            else:
                evidence_items.append("PagerDuty incident text mentions a deploy/change event")
            if anomalies:
                evidence_items.append(f"{anomalies[0].metric_name} = {anomalies[0].avg_value}")
            if alerts:
                evidence_items.append(f"Alert: {alerts[0].title}")

            changed_files = ", ".join((deploy.files_changed if deploy else [])[:3]) or "no file list available"
            deploy_description = (
                f"Recent deploy '{deploy.title}' at {deploy.timestamp} coincides with "
                f"error/latency/deploy-health anomaly. Changed files: {changed_files}."
                if deploy
                else "Incident text and telemetry point to a recent deploy or rollout change coinciding with the failure."
            )

            hypotheses.append(RootCauseHypothesis(
                rank=1,
                title=f"Deploy-related regression in {service}",
                description=deploy_description,
                confidence=confidence,
                supporting_evidence=evidence_items,
                source_signals=_unique_sources(
                    Source.GITHUB if evidence.github_events else None,
                    Source.DATADOG if evidence.metrics or evidence.alerts else None,
                    Source.PAGERDUTY,
                ),
            ))

        if has_external_outage:
            outage = status_outages[0]
            confidence = _compute_confidence(
                signal_count=len(evidence.status_events),
                alert_count=len(alerts),
                anomaly_count=len(anomalies),
                has_deploy=False,
            )
            hypotheses.append(RootCauseHypothesis(
                rank=2,
                title=f"Third-party dependency outage affecting {service}",
                description=f"{outage.service} is experiencing '{outage.status}' - {outage.description}",
                confidence=confidence,
                supporting_evidence=[
                    f"{outage.service} status: {outage.status}",
                    f"Affected: {', '.join(outage.affected_components) or 'not specified'}",
                    f"Error rate anomaly: {has_error_spike}",
                ],
                source_signals=_unique_sources(
                    Source.STATUSGATOR,
                    Source.DATADOG if evidence.metrics or evidence.alerts else None,
                ),
            ))

        if has_db_pressure:
            db_metric = db_anomalies[0] if db_anomalies else (anomalies[0] if anomalies else None)
            confidence = _compute_confidence(
                signal_count=len(evidence.metrics) + len(evidence.github_events),
                alert_count=len(alerts),
                anomaly_count=len(anomalies),
                has_deploy=has_recent_deploy,
            )
            metric_summary = (
                f"{db_metric.metric_name} at {db_metric.avg_value:.0f} active/waiting connections"
                if db_metric
                else "Incident text indicates database or connection-pool pressure"
            )
            supporting_evidence = [metric_summary]
            if alerts:
                supporting_evidence.append(f"Alert: {alerts[0].title}")
            if recent_deploys:
                supporting_evidence.append(f"Recent deploy: {recent_deploys[0].title}")

            hypotheses.append(RootCauseHypothesis(
                rank=3,
                title=f"Database capacity pressure on {service}",
                description=(
                    "Database connection pool is near capacity or queuing requests. "
                    f"Primary signal: {metric_summary}."
                ),
                confidence=confidence,
                supporting_evidence=supporting_evidence,
                source_signals=_unique_sources(
                    Source.DATADOG if evidence.metrics or evidence.alerts else None,
                    Source.GITHUB if evidence.github_events else None,
                    Source.PAGERDUTY,
                ),
            ))

        if not hypotheses:
            sources = _unique_sources(
                Source.DATADOG if evidence.metrics or evidence.alerts else None,
                Source.GITHUB if evidence.github_events else None,
                Source.STATUSGATOR if evidence.status_events else None,
                Source.PAGERDUTY,
            )
            hypotheses.append(RootCauseHypothesis(
                rank=1,
                title=f"Insufficient evidence for {service}",
                description="No strong root-cause signal detected. Possible causes: "
                            "transient traffic spike, partial infrastructure degradation, "
                            "or a configuration change not captured by the configured sources.",
                confidence=_compute_confidence(
                    signal_count=len(evidence.metrics) + len(evidence.github_events) + len(evidence.status_events),
                    alert_count=len(alerts),
                    anomaly_count=len(anomalies),
                    has_deploy=has_recent_deploy,
                ),
                supporting_evidence=[
                    f"{len(anomalies)} anomalous metrics found",
                    f"{len(alerts)} active alerts",
                    f"{len(evidence.github_events)} recent GitHub events",
                ],
                source_signals=sources,
            ))

        return hypotheses

    def _correlate_signals(self, evidence: IncidentEvidence) -> list[str]:
        notes = []
        incident_time = parse_timestamp(evidence.incident.created_at)

        for gh in evidence.github_events:
            deploy_time = parse_timestamp(gh.timestamp)
            if gh.type == "deploy" and incident_time and deploy_time and deploy_time <= incident_time:
                notes.append(
                    f"Signal correlation: Deploy '{gh.title}' "
                    f"at {gh.timestamp} preceded incident at {evidence.incident.created_at}"
                )

        for se in evidence.status_events:
            if se.incident:
                notes.append(
                    f"Signal correlation: {se.service} outage active during incident window"
                )

        return notes
