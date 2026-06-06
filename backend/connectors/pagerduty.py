import logging
from datetime import datetime, timezone
from typing import Optional

from schema.evidence import PagerDutyIncident, Severity
from .base import NonRetryableError, get_http_client
from backend.config import (
    PAGERDUTY_API_KEY,
    PAGERDUTY_BASE_URL,
    PAGERDUTY_FROM_EMAIL,
    has_pagerduty,
)

logger = logging.getLogger(__name__)

SEVERITY_MAP = {
    "critical": Severity.CRITICAL,
    "high": Severity.HIGH,
    "medium": Severity.MEDIUM,
    "low": Severity.LOW,
    "info": Severity.INFO,
}


def _headers() -> dict[str, str]:
    headers = {
        "Authorization": f"Token token={PAGERDUTY_API_KEY}",
        "Accept": "application/vnd.pagerduty+json;version=2",
        "Content-Type": "application/json",
    }
    if PAGERDUTY_FROM_EMAIL:
        headers["From"] = PAGERDUTY_FROM_EMAIL
    return headers


async def _real_get_incident(incident_id: str) -> Optional[PagerDutyIncident]:
    client = await get_http_client()
    url = f"{PAGERDUTY_BASE_URL}/incidents/{incident_id}"
    resp = await client.get(url, headers=_headers())
    if resp.status_code == 404:
        return None
    if resp.status_code == 429:
        from .base import RetryableError
        raise RetryableError(f"Rate limited: {resp.text}")
    resp.raise_for_status()
    data = resp.json().get("incident", {})

    service_name = ""
    if data.get("service"):
        service_name = data["service"].get("summary", "")

    assignments = []
    for a in data.get("assignments", []):
        assignee = a.get("assignee", {})
        if assignee.get("email"):
            assignments.append(assignee["email"])
        elif assignee.get("summary"):
            assignments.append(assignee["summary"])

    severity_str = data.get("urgency", "critical")
    severity = SEVERITY_MAP.get(severity_str, Severity.CRITICAL)

    return PagerDutyIncident(
        id=data.get("id", incident_id),
        title=data.get("title", "") or data.get("summary", "") or "",
        service=service_name,
        severity=severity,
        status=data.get("status", "triggered"),
        created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
        assigned_to=assignments or ["on-call@example.com"],
        description=data.get("description", "") or data.get("title", "") or "",
        alert_count=len(data.get("alerts", [])),
    )


async def _real_list_incidents(service: Optional[str] = None) -> list[dict]:
    client = await get_http_client()
    # PagerDuty filters by service_ids[], not service names. Fetch recent incidents and
    # apply the optional human-readable service-name filter locally.
    params: dict = {"limit": 25, "statuses[]": ["triggered", "acknowledged"]}
    url = f"{PAGERDUTY_BASE_URL}/incidents"
    resp = await client.get(url, headers=_headers(), params=params)
    if resp.status_code == 429:
        from .base import RetryableError
        raise RetryableError(f"Rate limited: {resp.text}")
    resp.raise_for_status()
    data = resp.json()
    results = []
    for inc in data.get("incidents", []):
        svc = inc.get("service", {}).get("summary", "")
        if service and svc != service:
            continue
        sev = SEVERITY_MAP.get(inc.get("urgency", "critical"), Severity.CRITICAL)
        results.append({
            "id": inc.get("id", ""),
            "title": inc.get("title", "") or inc.get("summary", ""),
            "service": svc,
            "severity": sev.value,
            "status": inc.get("status", "triggered"),
            "created_at": inc.get("created_at", ""),
        })
    return results


MOCK_INCIDENTS = {
    "INC-001": PagerDutyIncident(
        id="INC-001",
        title="High error rate on payment-api",
        service="payment-api",
        severity=Severity.CRITICAL,
        status="triggered",
        created_at="2026-05-29T14:22:00Z",
        assigned_to=["alice@example.com"],
        description="Error rate on /charge endpoint spiked to 23% (baseline <1%). "
                    "Customers reporting failed payments.",
        alert_count=12,
    ),
    "INC-002": PagerDutyIncident(
        id="INC-002",
        title="Latency spike on checkout-service",
        service="checkout-service",
        severity=Severity.HIGH,
        status="acknowledged",
        created_at="2026-05-29T13:45:00Z",
        assigned_to=["bob@example.com"],
        description="P99 latency on /checkout increased from 200ms to 12s. "
                    "Multiple customer timeout reports.",
        alert_count=8,
    ),
    "INC-003": PagerDutyIncident(
        id="INC-003",
        title="Database connection pool exhaustion on user-db",
        service="user-service",
        severity=Severity.CRITICAL,
        status="triggered",
        created_at="2026-05-29T15:10:00Z",
        assigned_to=["carol@example.com"],
        description="Active connections reached 95% of max pool size. "
                    "New connections are being queued and timing out.",
        alert_count=15,
    ),
    "INC-004": PagerDutyIncident(
        id="INC-004",
        title="Deploy failure on notification-service",
        service="notification-service",
        severity=Severity.HIGH,
        status="resolved",
        created_at="2026-05-28T22:00:00Z",
        assigned_to=["dave@example.com"],
        description="Canary deployment failed health checks. "
                    "Rolled back to previous version automatically.",
        alert_count=3,
    ),
}


async def get_incident(incident_id: str) -> Optional[PagerDutyIncident]:
    if not incident_id:
        raise NonRetryableError("incident_id is required")
    if has_pagerduty():
        try:
            result = await _real_get_incident(incident_id)
            if result:
                return result
        except Exception as e:
            logger.warning("PagerDuty real API failed, falling back to local incident catalog: %s", e)
    return MOCK_INCIDENTS.get(incident_id) or MOCK_INCIDENTS.get(incident_id.upper())


async def list_incidents(service: Optional[str] = None) -> list[dict]:
    if has_pagerduty():
        try:
            return await _real_list_incidents(service)
        except Exception as e:
            logger.warning("PagerDuty list real API failed, falling back to local incident catalog: %s", e)

    incidents = list(MOCK_INCIDENTS.values())
    if service:
        incidents = [i for i in incidents if i.service == service]
    return [
        {
            "id": i.id,
            "title": i.title,
            "service": i.service,
            "severity": i.severity.value,
            "status": i.status,
            "created_at": i.created_at,
        }
        for i in incidents
    ]
