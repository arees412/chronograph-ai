"""Deterministic utility functions and sanitization boundaries."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from chronograph_ai.models import Sensitivity

NAMESPACE = uuid.UUID("8c6d7d86-c006-4c98-834f-d81c94775884")
SENSITIVE_KEYS = re.compile(
    r"(?:api[_-]?key|authorization|cookie|password|secret|token)", re.IGNORECASE
)
SECRET_VALUE = re.compile(
    r"(?:gh[pousr]_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|bearer\s+[A-Za-z0-9._-]+)",
    re.IGNORECASE,
)
SENSITIVITY_ORDER = {
    Sensitivity.PUBLIC: 0,
    Sensitivity.INTERNAL: 1,
    Sensitivity.CONFIDENTIAL: 2,
    Sensitivity.PII: 3,
    Sensitivity.RESTRICTED: 4,
}


def utc_now() -> datetime:
    return datetime.now(UTC)


def normalize_name(value: str) -> str:
    folded = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.sub(r"[^\w]+", " ", folded, flags=re.UNICODE).split())


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def digest(value: Any) -> str:
    return content_hash(canonical_json(value))


def stable_id(kind: str, *parts: object) -> str:
    payload = "|".join([kind, *(canonical_json(part) for part in parts)])
    return str(uuid.uuid5(NAMESPACE, payload))


def interval_contains(start: datetime, end: datetime | None, point: datetime) -> bool:
    return start <= point and (end is None or point < end)


def intervals_overlap(
    left_start: datetime,
    left_end: datetime | None,
    right_start: datetime,
    right_end: datetime | None,
) -> bool:
    return (left_end is None or right_start < left_end) and (
        right_end is None or left_start < right_end
    )


def max_sensitivity(*values: Sensitivity) -> Sensitivity:
    return max(values, key=SENSITIVITY_ORDER.__getitem__)


def tokenize(value: str) -> list[str]:
    return [token for token in normalize_name(value).split() if len(token) > 1]


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def sanitize(value: Any) -> Any:
    """Redact common secrets without claiming complete sensitive-data detection."""

    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if SENSITIVE_KEYS.search(str(key)) else sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        return SECRET_VALUE.sub("[REDACTED]", value)
    return value
