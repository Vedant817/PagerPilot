import re
import logging

logger = logging.getLogger(__name__)

SENSITIVE_PATTERNS = [
    (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'), '[EMAIL REDACTED]'),
    (re.compile(r'\b(token|secret|api[_-]?key|password)\s*[:=]\s*\S+', re.IGNORECASE), r'\1: [REDACTED]'),
    (re.compile(r'\b[A-Za-z0-9+/]{40,}\b'), '[TOKEN REDACTED]'),
]


def redact_sensitive(value: str) -> str:
    for pattern, replacement in SENSITIVE_PATTERNS:
        if pattern.groups:
            value = pattern.sub(lambda m: f"{m.group(1)}: [REDACTED]", value)
        else:
            value = pattern.sub(replacement, value)
    return value


def redact_dict(data: dict) -> dict:
    result = {}
    for key, val in data.items():
        if isinstance(val, str):
            result[key] = redact_sensitive(val)
        elif isinstance(val, dict):
            result[key] = redact_dict(val)
        elif isinstance(val, list):
            result[key] = [redact_sensitive(v) if isinstance(v, str) else v for v in val]
        else:
            result[key] = val
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
