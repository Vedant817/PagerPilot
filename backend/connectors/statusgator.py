import logging
from typing import Optional

from backend.config import STATUSGATOR_API_KEY, STATUSGATOR_BASE_URL, has_statusgator
from schema.evidence import StatusGatorEvent
from .base import NonRetryableError, RetryableError, get_http_client

logger = logging.getLogger(__name__)


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Token {STATUSGATOR_API_KEY}",
        "Accept": "application/json",
    }


async def get_service_status(service_name: str) -> Optional[StatusGatorEvent]:
    if not service_name:
        raise NonRetryableError("service_name is required")
    if not has_statusgator():
        logger.warning("StatusGator not configured, returning None for %s", service_name)
        return None

    components = await _fetch_all_components()
    for comp in components:
        if comp.service.lower() == service_name.lower():
            return comp

    logger.warning("Status not found for service: %s", service_name)
    return None


async def get_all_statuses() -> list[StatusGatorEvent]:
    if not has_statusgator():
        logger.warning("StatusGator not configured, returning empty list")
        return []

    return await _fetch_all_components()


async def _fetch_all_components() -> list[StatusGatorEvent]:
    client = await get_http_client()
    url = f"{STATUSGATOR_BASE_URL}/components"

    resp = await client.get(url, headers=_headers())
    if resp.status_code == 429:
        raise RetryableError(f"StatusGator rate limited: {resp.text}")
    if resp.status_code in (401, 403):
        raise NonRetryableError(f"StatusGator auth failed: {resp.text}")
    if resp.status_code != 200:
        logger.warning("StatusGator returned %s", resp.status_code)
        return []

    data = resp.json()
    components = data if isinstance(data, list) else data.get("components", data.get("data", []))

    events: list[StatusGatorEvent] = []
    for comp in components:
        name = comp.get("name", "")
        status = comp.get("status", comp.get("status_label", "unknown"))
        description = comp.get("description", comp.get("status_description", ""))
        last_updated = comp.get("updated_at", comp.get("last_updated", ""))
        incident = bool(comp.get("incident", False)) or status.lower() not in (
            "operational", "active", "none", "ok"
        )

        affected = comp.get("affected_components", comp.get("components", []))
        if isinstance(affected, list):
            affected = [a.get("name", str(a)) if isinstance(a, dict) else str(a) for a in affected]
        else:
            affected = []

        events.append(StatusGatorEvent(
            service=name,
            status=status,
            incident=incident,
            title=comp.get("title", comp.get("name", name)),
            description=description,
            last_updated=last_updated,
            affected_components=affected,
        ))

    return events
