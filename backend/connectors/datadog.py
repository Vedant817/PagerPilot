import logging
from typing import Optional

import httpx

from schema.evidence import DatadogMetric, DatadogAlert, Severity
from .base import NonRetryableError, RetryableError, get_http_client
from backend.config import (
    has_datadog, DATADOG_API_KEY, DATADOG_APP_KEY, DATADOG_BASE_URL,
    DATADOG_METRIC_QUERIES, DATADOG_MONITOR_TAGS,
)

logger = logging.getLogger(__name__)

SEVERITY_MAP: dict[str, Severity] = {
    "Alert": Severity.CRITICAL,
    "Warning": Severity.HIGH,
    "Info": Severity.MEDIUM,
    "None": Severity.INFO,
}


def _headers() -> dict[str, str]:
    return {
        "DD-API-KEY": DATADOG_API_KEY,
        "DD-APPLICATION-KEY": DATADOG_APP_KEY,
    }


async def get_service_metrics(service: str, window: str = "1h") -> list[DatadogMetric]:
    if not service:
        raise NonRetryableError("service is required")
    if not has_datadog():
        logger.warning(f"Datadog not configured, returning empty metrics for {service}")
        return []

    client = await get_http_client()
    metric_queries = DATADOG_METRIC_QUERIES.get(service, [])
    if not metric_queries:
        logger.warning(f"No metric queries configured for service {service}")
        return []

    results: list[DatadogMetric] = []
    for query in metric_queries:
        try:
            metric = await _query_metric(client, query, service, window)
            if metric:
                results.append(metric)
        except Exception as e:
            logger.warning(f"Failed to query Datadog metric '{query}' for {service}: {e}")

    return results


async def _query_metric(
    client: httpx.AsyncClient,
    query: str,
    service: str,
    window: str,
) -> Optional[DatadogMetric]:
    url = f"{DATADOG_BASE_URL}/api/v1/query"
    params = {
        "query": query,
        "from": _window_to_from_ts(window),
        "to": _now_ts(),
    }

    resp = await client.get(url, headers=_headers(), params=params)
    if resp.status_code == 429:
        raise RetryableError(f"Datadog rate limited: {resp.text}")
    if resp.status_code == 403:
        raise NonRetryableError(f"Datadog auth failed: {resp.text}")
    resp.raise_for_status()

    data = resp.json()
    series = data.get("series", [])
    if not series:
        logger.debug(f"No series returned for query: {query}")
        return None

    points = series[0].get("pointlist", [])
    if not points:
        return None

    avg_val = sum(p[1] for p in points if p[1] is not None) / max(len([p for p in points if p[1] is not None]), 1)
    p99_val = avg_val

    filtered = [p[1] for p in points if p[1] is not None]
    if len(filtered) > 1:
        sorted_vals = sorted(filtered)
        idx = int(len(sorted_vals) * 0.99)
        p99_val = sorted_vals[min(idx, len(sorted_vals) - 1)]

    metric_name = series[0].get("metric", query.split("{")[0].strip())
    anomaly = _detect_anomaly(filtered) if len(filtered) > 1 else False

    return DatadogMetric(
        metric_name=metric_name,
        service=service,
        avg_value=round(avg_val, 2),
        p99_value=round(p99_val, 2),
        anomaly=anomaly,
        window=window,
        unit=series[0].get("unit", ""),
    )


async def get_service_alerts(service: str) -> list[DatadogAlert]:
    if not service:
        raise NonRetryableError("service is required")
    if not has_datadog():
        logger.warning(f"Datadog not configured, returning empty alerts for {service}")
        return []

    client = await get_http_client()
    url = f"{DATADOG_BASE_URL}/api/v1/monitor"
    params: dict = {
        "group_states": "alert,warn,no data",
        "tags": DATADOG_MONITOR_TAGS if DATADOG_MONITOR_TAGS else f"service:{service}",
    }

    resp = await client.get(url, headers=_headers(), params=params)
    if resp.status_code == 429:
        raise RetryableError(f"Datadog rate limited: {resp.text}")
    if resp.status_code == 403:
        raise NonRetryableError(f"Datadog auth failed: {resp.text}")
    resp.raise_for_status()

    monitors = resp.json()
    alerts: list[DatadogAlert] = []

    for mon in monitors:
        overall_state = mon.get("overall_state", "")
        if overall_state not in ("Alert", "Warning", "No Data"):
            continue

        mon_query = mon.get("query", "")
        if service not in mon_query and f"service:{service}" not in mon_query:
            continue

        last_triggered = mon.get("last_triggered_ts")
        triggered_at = str(last_triggered) if last_triggered else ""

        alerts.append(DatadogAlert(
            id=str(mon.get("id", "")),
            title=mon.get("name", ""),
            service=service,
            status=overall_state.lower(),
            severity=SEVERITY_MAP.get(overall_state, Severity.HIGH),
            query=mon_query,
            triggered_at=triggered_at,
            value=0.0,
            threshold=float(mon.get("options", {}).get("thresholds", {}).get("critical", 0)),
        ))

    return alerts


def _detect_anomaly(values: list[float]) -> bool:
    if len(values) < 3:
        return False
    recent = values[-1]
    mean = sum(values[:-1]) / len(values[:-1])
    if mean == 0:
        return recent > 1.0
    ratio = recent / mean
    return ratio > 2.0 or ratio < 0.5


def _window_to_from_ts(window: str) -> int:
    import time
    now = int(time.time())
    unit = window[-1]
    try:
        value = int(window[:-1])
    except ValueError:
        return now - 3600

    multipliers = {"h": 3600, "m": 60, "d": 86400}
    return now - (value * multipliers.get(unit, 3600))


def _now_ts() -> int:
    import time
    return int(time.time())
