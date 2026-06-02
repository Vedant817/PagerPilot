import logging
from schema.evidence import (
    IncidentEvidence, RootCauseHypothesis, Source,
)
from backend.agents.base import BaseAgent, AgentResult
from backend.config import analysis_rules_for_service

logger = logging.getLogger(__name__)


def _compute_confidence(signal_count: int, alert_count: int, anomaly_count: int, has_deploy: bool) -> float:
    base = 0.2
    if has_deploy:
        base += 0.15
    base += min(signal_count * 0.1, 0.3)
    if alert_count > 0:
        base += min(alert_count * 0.05, 0.15)
    if anomaly_count > 0:
        base += min(anomaly_count * 0.05, 0.1)
    base += min(anomaly_count * 0.03, 0.1)
    return round(min(base, 0.95), 2)


def _matches_rule(metric_name: str, rule_keywords: list[str]) -> bool:
    return any(kw.lower() in metric_name.lower() for kw in rule_keywords)


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

        logger.info(
            f"AnalystAgent: generated {len(hypotheses)} ranked hypotheses"
        )

        return AgentResult(True, data={
            "hypotheses": hypotheses,
            "hypothesis_count": len(hypotheses),
            "top_hypothesis": hypotheses[0].title if hypotheses else None,
        })

    def _rank_hypotheses(self, evidence: IncidentEvidence) -> list[RootCauseHypothesis]:
        hypotheses = []
        service = evidence.incident.service

        recent_deploys = [e for e in evidence.github_events if e.type == "deploy"]
        has_recent_deploy = len(recent_deploys) > 0

        status_outages = [s for s in evidence.status_events if s.incident]
        has_external_outage = len(status_outages) > 0

        anomalies = [m for m in evidence.metrics if m.anomaly]
        alerts = evidence.alerts
        rules = analysis_rules_for_service(service)

        error_keywords = rules.get("error_keywords", ["error", "fault", "exception", "fail"])
        latency_keywords = rules.get("latency_keywords", ["latency", "p99", "p95", "response_time"])
        db_keywords = rules.get("db_keywords", ["db.connections", "database", "connection_pool", "pg_stat"])
        deploy_keywords = rules.get("deploy_keywords", ["deploy", "health", "canary", "rollout"])

        has_error_spike = any(
            _matches_rule(m.metric_name, error_keywords) and m.anomaly
            for m in evidence.metrics
        )
        has_latency_spike = any(
            _matches_rule(m.metric_name, latency_keywords) and m.anomaly
            for m in evidence.metrics
        )
        has_db_pressure = any(
            _matches_rule(m.metric_name, db_keywords) and m.anomaly
            for m in evidence.metrics
        )
        has_deploy_failure = any(
            _matches_rule(m.metric_name, deploy_keywords) and m.anomaly
            for m in evidence.metrics
        )

        if has_recent_deploy and (has_error_spike or has_latency_spike or has_deploy_failure):
            deploy = recent_deploys[0]
            confidence = _compute_confidence(
                signal_count=len(evidence.github_events) + len(evidence.metrics),
                alert_count=len(alerts),
                anomaly_count=len(anomalies),
                has_deploy=True,
            )
            evidence_items = [
                f"Deploy at {deploy.timestamp}",
            ]
            if anomalies:
                evidence_items.append(f"{anomalies[0].metric_name} = {anomalies[0].avg_value}")
            if alerts:
                evidence_items.append(f"Alert: {alerts[0].title}")

            hypotheses.append(RootCauseHypothesis(
                rank=1,
                title=f"Deploy-related regression in {service}",
                description=f"Recent deploy '{deploy.title}' at {deploy.timestamp} "
                            f"coincides with error/latency anomaly. "
                            f"Changed files: {', '.join(deploy.files_changed[:3])}.",
                confidence=confidence,
                supporting_evidence=evidence_items,
                source_signals=[Source.GITHUB, Source.DATADOG],
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
                description=f"{outage.service} is experiencing '{outage.status}' - "
                            f"{outage.description}",
                confidence=confidence,
                supporting_evidence=[
                    f"{outage.service} status: {outage.status}",
                    f"Affected: {', '.join(outage.affected_components)}",
                    f"Error rate anomaly: {has_error_spike}",
                ],
                source_signals=[Source.STATUSGATOR, Source.DATADOG],
            ))

        if has_db_pressure:
            db_metric = anomalies[0]
            confidence = _compute_confidence(
                signal_count=len(evidence.metrics),
                alert_count=len(alerts),
                anomaly_count=len(anomalies),
                has_deploy=has_recent_deploy,
            )
            hypotheses.append(RootCauseHypothesis(
                rank=3,
                title=f"Database capacity pressure on {service}",
                description="Database connection pool near max capacity with "
                            f"{db_metric.avg_value:.0f} active connections. "
                            "New connections being queued.",
                confidence=confidence,
                supporting_evidence=[
                    f"{db_metric.metric_name}: {db_metric.avg_value}",
                    "Active connections near limit",
                ],
                source_signals=[Source.DATADOG],
            ))

        if not hypotheses:
            hypotheses.append(RootCauseHypothesis(
                rank=1,
                title=f"Insufficient evidence for {service}",
                description="No strong root cause signal detected. Possible causes: "
                            "transient traffic spike, partial infrastructure degradation, "
                            "or configuration change not tracked via GitHub.",
                confidence=_compute_confidence(
                    signal_count=0,
                    alert_count=len(alerts),
                    anomaly_count=len(anomalies),
                    has_deploy=has_recent_deploy,
                ),
                supporting_evidence=[
                    f"{len(anomalies)} anomalous metrics found",
                    f"{len(alerts)} active alerts",
                ],
                source_signals=[Source.DATADOG, Source.PAGERDUTY],
            ))

        return hypotheses

    def _correlate_signals(self, evidence: IncidentEvidence) -> list[str]:
        notes = []
        incident_time = evidence.incident.created_at

        for gh in evidence.github_events:
            if gh.type == "deploy" and gh.timestamp <= incident_time:
                notes.append(
                    f"Signal correlation: Deploy '{gh.title}' "
                    f"at {gh.timestamp} preceded incident at {incident_time}"
                )

        for se in evidence.status_events:
            if se.incident:
                notes.append(
                    f"Signal correlation: {se.service} outage active "
                    "during incident window"
                )

        return notes
