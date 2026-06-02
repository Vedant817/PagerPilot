from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class Source(str, Enum):
    PAGERDUTY = "pagerduty"
    DATADOG = "datadog"
    GITHUB = "github"
    STATUSGATOR = "statusgator"


@dataclass
class PagerDutyIncident:
    id: str
    title: str
    service: str
    severity: Severity
    status: str
    created_at: str
    assigned_to: list[str]
    description: str
    alert_count: int = 0


@dataclass
class DatadogMetric:
    metric_name: str
    service: str
    avg_value: float
    p99_value: float
    anomaly: bool
    window: str
    unit: str = ""


@dataclass
class DatadogAlert:
    id: str
    title: str
    service: str
    status: str
    severity: Severity
    query: str
    triggered_at: str
    value: float
    threshold: float


@dataclass
class GitHubEvent:
    type: str  # deploy, pr, commit, release
    repo: str
    title: str
    author: str
    timestamp: str
    sha: str = ""
    pr_number: int = 0
    description: str = ""
    files_changed: list[str] = field(default_factory=list)


@dataclass
class StatusGatorEvent:
    service: str
    status: str
    incident: bool
    title: str
    description: str
    last_updated: str
    affected_components: list[str] = field(default_factory=list)


@dataclass
class IncidentEvidence:
    incident: PagerDutyIncident
    metrics: list[DatadogMetric] = field(default_factory=list)
    alerts: list[DatadogAlert] = field(default_factory=list)
    github_events: list[GitHubEvent] = field(default_factory=list)
    status_events: list[StatusGatorEvent] = field(default_factory=list)
    correlation_notes: list[str] = field(default_factory=list)


@dataclass
class RootCauseHypothesis:
    rank: int
    title: str
    description: str
    confidence: float
    supporting_evidence: list[str]
    source_signals: list[Source]


@dataclass
class ServiceImpact:
    affected_service: str
    downstream_services: list[str]
    external_dependencies_impacted: list[str]
    customer_facing: bool
    estimated_blast_percentage: int
    affected_endpoints: list[str]


@dataclass
class IncidentBrief:
    incident_id: str
    title: str
    service: str
    severity: Severity
    status: str
    summary: str
    timeline: list[dict]
    root_cause_hypotheses: list[RootCauseHypothesis]
    recommended_action: str
    evidence_sources: list[Source]
    generated_at: str
    confidence_score: float
    service_impact: Optional["ServiceImpact"] = None
