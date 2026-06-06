import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

SENSITIVE_PATTERNS = [
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[EMAIL REDACTED]"),
    (re.compile(r"\b(token|secret|api[_-]?key|password)\s*[:=]\s*\S+", re.IGNORECASE), None),
    (re.compile(r"\b[A-Za-z0-9+/]{40,}\b"), "[TOKEN REDACTED]"),
]

SENSITIVE_KEYWORDS = ("token", "secret", "api_key", "apikey", "password", "authorization")


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def redact_sensitive(value: Any) -> str:
    text = _stringify(value)
    for pattern, replacement in SENSITIVE_PATTERNS:
        if replacement is None:
            text = pattern.sub(lambda m: f"{m.group(1)}: [REDACTED]", text)
        else:
            text = pattern.sub(replacement, text)
    return text


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_sensitive(value)
    if isinstance(value, dict):
        return redact_dict(value)
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value


def redact_dict(data: dict) -> dict:
    result = {}
    for key, val in data.items():
        key_text = str(key)
        if any(marker in key_text.lower().replace("-", "_") for marker in SENSITIVE_KEYWORDS):
            result[key] = "[REDACTED]"
        else:
            result[key] = _redact_value(val)
    return result


def validate_json_schema(data: dict, schema: dict) -> list[str]:
    errors = []
    for key, type_hint in schema.items():
        if key not in data:
            errors.append(f"Missing required key: {key}")
            continue
        if type_hint == "list" and not isinstance(data[key], list):
            errors.append(f"Key '{key}' should be a list")
        elif type_hint == "dict" and not isinstance(data[key], dict):
            errors.append(f"Key '{key}' should be a dict")
        elif type_hint == "str" and not isinstance(data[key], str):
            errors.append(f"Key '{key}' should be a string")
    return errors
