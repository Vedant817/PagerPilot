import copy
import json
import logging
import os
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - keeps config importable if optional dep is absent
    def load_dotenv(*_args, **_kwargs):
        return False

logger = logging.getLogger(__name__)

env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)


DEFAULT_DATADOG_METRIC_QUERIES: dict[str, list[str]] = {
    "payment-api": [
        "avg:request.error.rate{service:payment-api}",
        "p99:request.latency{service:payment-api}",
    ],
    "checkout-service": [
        "p99:request.latency{service:checkout-service}",
        "avg:request.error.rate{service:checkout-service}",
    ],
    "user-service": [
        "avg:db.connections.active{service:user-service}",
        "avg:db.connections.waiting{service:user-service}",
    ],
    "notification-service": [
        "avg:deploy.health.failed{service:notification-service}",
        "avg:request.error.rate{service:notification-service}",
    ],
}

DEFAULT_SERVICE_OWNER_MAP: dict[str, str] = {
    "payment-api": "yourorg/payment-api",
    "checkout-service": "yourorg/checkout-service",
    "user-service": "yourorg/user-service",
    "notification-service": "yourorg/notification-service",
}

DEFAULT_EXTERNAL_DEPENDENCY_MAP: dict[str, list[str]] = {
    "payment-api": ["stripe"],
    "checkout-service": ["stripe", "aws-us-east-1"],
    "user-service": ["aws-us-east-1"],
    "notification-service": ["datadog"],
}

DEFAULT_SERVICE_DEPENDENCY_GRAPH: dict[str, dict[str, Any]] = {
    "payment-api": {
        "downstream": ["checkout-service", "notification-service"],
        "endpoints": ["/charge", "/refund", "/webhook"],
        "customer_facing": True,
    },
    "checkout-service": {
        "downstream": ["notification-service"],
        "endpoints": ["/checkout", "/cart", "/pricing"],
        "customer_facing": True,
    },
    "user-service": {
        "downstream": ["payment-api", "checkout-service", "notification-service"],
        "endpoints": ["/login", "/session", "/profile"],
        "customer_facing": True,
    },
    "notification-service": {
        "downstream": [],
        "endpoints": ["/email", "/sms", "/webhook"],
        "customer_facing": False,
    },
}

DEFAULT_ANALYSIS_RULES: dict[str, dict[str, list[str]]] = {
    "default": {
        "error_keywords": ["error", "fault", "exception", "fail", "failed", "failure"],
        "latency_keywords": ["latency", "p99", "p95", "response_time", "timeout", "slow"],
        "db_keywords": [
            "db.connections", "database", "connection_pool", "connection pool",
            "pg_stat", "active connections",
        ],
        "deploy_keywords": [
            "deploy", "deployed", "deployment", "health", "canary",
            "rollout", "rollback", "release",
        ],
    }
}

DEFAULT_BLAST_RADIUS_MAP: dict[str, int] = {
    "deploy": 60,
    "regression": 60,
    "dependency": 80,
    "third-party": 80,
    "database": 40,
    "capacity": 40,
    "default": 20,
}


def _json_env(name: str, default: Any) -> Any:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return copy.deepcopy(default)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("%s is not valid JSON, using defaults", name)
        return copy.deepcopy(default)


def _dict_env(name: str, default: dict) -> dict:
    value = _json_env(name, default)
    if not isinstance(value, dict):
        logger.warning("%s must be a JSON object, using defaults", name)
        return copy.deepcopy(default)
    return value


def _int_env(name: str, default: int, min_value: int | None = None) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("%s must be an integer, using default %s", name, default)
        return default
    if min_value is not None and value < min_value:
        logger.warning("%s must be >= %s, using default %s", name, min_value, default)
        return default
    return value


def _csv_env(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


CORS_ORIGINS = _csv_env("CORS_ORIGINS", ["*"])

PAGERDUTY_API_KEY = os.environ.get("PAGERDUTY_API_KEY") or ""
PAGERDUTY_FROM_EMAIL = os.environ.get("PAGERDUTY_FROM_EMAIL") or ""
PAGERDUTY_BASE_URL = os.environ.get("PAGERDUTY_BASE_URL", "https://api.pagerduty.com")

DATADOG_API_KEY = os.environ.get("DATADOG_API_KEY") or ""
DATADOG_APP_KEY = os.environ.get("DATADOG_APP_KEY") or ""
DATADOG_SITE = os.environ.get("DATADOG_SITE", "datadoghq.com")
DATADOG_BASE_URL = f"https://api.{DATADOG_SITE}"
DATADOG_MONITOR_TAGS = os.environ.get("DATADOG_MONITOR_TAGS", "")
DATADOG_METRIC_QUERIES: dict[str, list[str]] = _dict_env(
    "DATADOG_METRIC_QUERIES", DEFAULT_DATADOG_METRIC_QUERIES
)

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN") or ""
GITHUB_BASE_URL = os.environ.get("GITHUB_BASE_URL", "https://api.github.com")

STATUSGATOR_API_KEY = os.environ.get("STATUSGATOR_API_KEY") or ""
STATUSGATOR_BASE_URL = os.environ.get("STATUSGATOR_BASE_URL", "https://api.statusgator.com/v2")

SERVICE_OWNER_MAP: dict[str, str] = _dict_env("SERVICE_OWNER_MAP", DEFAULT_SERVICE_OWNER_MAP)
EXTERNAL_DEPENDENCY_MAP: dict[str, list[str]] = _dict_env(
    "EXTERNAL_DEPENDENCY_MAP", DEFAULT_EXTERNAL_DEPENDENCY_MAP
)
SERVICE_DEPENDENCY_GRAPH: dict[str, dict[str, Any]] = _dict_env(
    "SERVICE_DEPENDENCY_GRAPH", DEFAULT_SERVICE_DEPENDENCY_GRAPH
)
ANALYSIS_RULES: dict[str, dict[str, list[str]]] = _dict_env("ANALYSIS_RULES", DEFAULT_ANALYSIS_RULES)
BLAST_RADIUS_MAP: dict[str, int] = _dict_env("BLAST_RADIUS_MAP", DEFAULT_BLAST_RADIUS_MAP)

SESSION_MAX_AGE_SECONDS = _int_env("SESSION_MAX_AGE_SECONDS", 86400, min_value=60)
SESSION_MAX_LOGS = _int_env("SESSION_MAX_LOGS", 500, min_value=10)
SESSION_MAX_SESSIONS = _int_env("SESSION_MAX_SESSIONS", 1000, min_value=1)


def has_pagerduty() -> bool:
    return bool(PAGERDUTY_API_KEY)


def has_datadog() -> bool:
    return bool(DATADOG_API_KEY) and bool(DATADOG_APP_KEY)


def has_github() -> bool:
    return bool(GITHUB_TOKEN)


def has_statusgator() -> bool:
    return bool(STATUSGATOR_API_KEY)


def repo_for_service(service_name: str) -> str:
    if not service_name:
        return ""
    repo = SERVICE_OWNER_MAP.get(service_name, f"pagerpilot/{service_name}")
    return str(repo) if repo else ""


def metric_queries_for_service(service_name: str) -> list[str]:
    queries = DATADOG_METRIC_QUERIES.get(service_name, [])
    if not isinstance(queries, list):
        logger.warning("Metric queries for %s must be a list, ignoring", service_name)
        return []
    return [str(query) for query in queries if query]


def external_deps_for_service(service_name: str) -> list[str]:
    deps = EXTERNAL_DEPENDENCY_MAP.get(service_name, [])
    if not isinstance(deps, list):
        logger.warning("External dependency map for %s must be a list, ignoring", service_name)
        return []
    return [str(dep) for dep in deps if dep]


def dependency_graph_for_service(service_name: str) -> dict[str, Any]:
    default = {"downstream": [], "endpoints": [], "customer_facing": True}
    configured = SERVICE_DEPENDENCY_GRAPH.get(service_name, {})
    if not isinstance(configured, dict):
        logger.warning("Dependency graph for %s must be an object, using defaults", service_name)
        configured = {}
    merged = {**default, **configured}
    downstream = merged.get("downstream") or []
    endpoints = merged.get("endpoints") or []
    merged["downstream"] = [str(item) for item in downstream] if isinstance(downstream, list) else []
    merged["endpoints"] = [str(item) for item in endpoints] if isinstance(endpoints, list) else []
    merged["customer_facing"] = bool(merged.get("customer_facing", True))
    return merged


def analysis_rules_for_service(service_name: str) -> dict[str, list[str]]:
    default = ANALYSIS_RULES.get("default", DEFAULT_ANALYSIS_RULES["default"])
    if not isinstance(default, dict):
        default = DEFAULT_ANALYSIS_RULES["default"]
    service_rules = ANALYSIS_RULES.get(service_name, {})
    if not isinstance(service_rules, dict):
        logger.warning("Analysis rules for %s must be an object, using defaults", service_name)
        service_rules = {}

    merged = {**default, **service_rules}
    normalized: dict[str, list[str]] = {}
    for key, value in merged.items():
        if isinstance(value, list):
            normalized[key] = [str(item) for item in value]
        else:
            logger.warning("Analysis rule %s for %s must be a list, ignoring", key, service_name)
            normalized[key] = []
    return normalized


def blast_radius_for_hypothesis(hypothesis_title: str) -> int:
    title = hypothesis_title.lower()
    for keyword, pct in BLAST_RADIUS_MAP.items():
        if keyword == "default":
            continue
        if keyword.lower() in title:
            try:
                return int(pct)
            except (TypeError, ValueError):
                return DEFAULT_BLAST_RADIUS_MAP["default"]
    try:
        return int(BLAST_RADIUS_MAP.get("default", DEFAULT_BLAST_RADIUS_MAP["default"]))
    except (TypeError, ValueError):
        return DEFAULT_BLAST_RADIUS_MAP["default"]
