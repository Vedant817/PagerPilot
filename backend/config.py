import os
import json
import logging
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)


PAGERDUTY_API_KEY = os.environ.get("PAGERDUTY_API_KEY") or ""
PAGERDUTY_FROM_EMAIL = os.environ.get("PAGERDUTY_FROM_EMAIL") or ""
PAGERDUTY_BASE_URL = os.environ.get("PAGERDUTY_BASE_URL", "https://api.pagerduty.com")


DATADOG_API_KEY = os.environ.get("DATADOG_API_KEY") or ""
DATADOG_APP_KEY = os.environ.get("DATADOG_APP_KEY") or ""
DATADOG_SITE = os.environ.get("DATADOG_SITE", "datadoghq.com")
DATADOG_BASE_URL = f"https://api.{DATADOG_SITE}"


GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN") or ""
GITHUB_BASE_URL = os.environ.get("GITHUB_BASE_URL", "https://api.github.com")


STATUSGATOR_API_KEY = os.environ.get("STATUSGATOR_API_KEY") or ""
STATUSGATOR_BASE_URL = os.environ.get("STATUSGATOR_BASE_URL", "https://api.statusgator.com/v2")


SERVICE_OWNER_MAP_RAW = os.environ.get("SERVICE_OWNER_MAP", "{}")
try:
    SERVICE_OWNER_MAP: dict[str, str] = json.loads(SERVICE_OWNER_MAP_RAW)
except json.JSONDecodeError:
    logger.warning("SERVICE_OWNER_MAP is not valid JSON, using defaults")
    SERVICE_OWNER_MAP = {}

DATADOG_METRIC_QUERIES_RAW = os.environ.get("DATADOG_METRIC_QUERIES", "{}")
try:
    DATADOG_METRIC_QUERIES: dict[str, list[str]] = json.loads(DATADOG_METRIC_QUERIES_RAW)
except json.JSONDecodeError:
    logger.warning("DATADOG_METRIC_QUERIES is not valid JSON, using defaults")
    DATADOG_METRIC_QUERIES = {}

DATADOG_MONITOR_TAGS = os.environ.get("DATADOG_MONITOR_TAGS", "")


EXTERNAL_DEPENDENCY_MAP_RAW = os.environ.get("EXTERNAL_DEPENDENCY_MAP", "{}")
try:
    EXTERNAL_DEPENDENCY_MAP: dict[str, list[str]] = json.loads(EXTERNAL_DEPENDENCY_MAP_RAW)
except json.JSONDecodeError:
    logger.warning("EXTERNAL_DEPENDENCY_MAP is not valid JSON, using defaults")
    EXTERNAL_DEPENDENCY_MAP = {}

SERVICE_DEPENDENCY_GRAPH_RAW = os.environ.get("SERVICE_DEPENDENCY_GRAPH", "{}")
try:
    SERVICE_DEPENDENCY_GRAPH: dict[str, dict] = json.loads(SERVICE_DEPENDENCY_GRAPH_RAW)
except json.JSONDecodeError:
    logger.warning("SERVICE_DEPENDENCY_GRAPH is not valid JSON, using defaults")
    SERVICE_DEPENDENCY_GRAPH = {}

ANALYSIS_RULES_RAW = os.environ.get("ANALYSIS_RULES", "{}")
try:
    ANALYSIS_RULES: dict[str, list[str]] = json.loads(ANALYSIS_RULES_RAW)
except json.JSONDecodeError:
    logger.warning("ANALYSIS_RULES is not valid JSON, using defaults")
    ANALYSIS_RULES = {}

BLAST_RADIUS_MAP_RAW = os.environ.get("BLAST_RADIUS_MAP", "{}")
try:
    BLAST_RADIUS_MAP: dict[str, int] = json.loads(BLAST_RADIUS_MAP_RAW)
except json.JSONDecodeError:
    logger.warning("BLAST_RADIUS_MAP is not valid JSON, using defaults")
    BLAST_RADIUS_MAP = {}

SESSION_MAX_AGE_SECONDS = int(os.environ.get("SESSION_MAX_AGE_SECONDS", "86400"))
SESSION_MAX_LOGS = int(os.environ.get("SESSION_MAX_LOGS", "500"))
SESSION_MAX_SESSIONS = int(os.environ.get("SESSION_MAX_SESSIONS", "1000"))


def has_pagerduty() -> bool:
    return bool(PAGERDUTY_API_KEY)


def has_datadog() -> bool:
    return bool(DATADOG_API_KEY) and bool(DATADOG_APP_KEY)


def has_github() -> bool:
    return bool(GITHUB_TOKEN)


def has_statusgator() -> bool:
    return bool(STATUSGATOR_API_KEY)


def repo_for_service(service_name: str) -> str:
    return SERVICE_OWNER_MAP.get(service_name, f"pagerpilot/{service_name}")


def metric_queries_for_service(service_name: str) -> list[str]:
    return DATADOG_METRIC_QUERIES.get(service_name, [])


def external_deps_for_service(service_name: str) -> list[str]:
    return EXTERNAL_DEPENDENCY_MAP.get(service_name, [])


def dependency_graph_for_service(service_name: str) -> dict:
    default = {"downstream": [], "endpoints": [], "customer_facing": True}
    return SERVICE_DEPENDENCY_GRAPH.get(service_name, default)


def analysis_rules_for_service(service_name: str) -> dict[str, list[str]]:
    return ANALYSIS_RULES.get(service_name, {})


def blast_radius_for_hypothesis(hypothesis_title: str) -> int:
    for keyword, pct in BLAST_RADIUS_MAP.items():
        if keyword.lower() in hypothesis_title.lower():
            return pct
    return BLAST_RADIUS_MAP.get("default", 20)
