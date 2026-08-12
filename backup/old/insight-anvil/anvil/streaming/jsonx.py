from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

import orjson


def _default(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def dumps(data: dict) -> bytes:
    return orjson.dumps(data, default=_default, option=orjson.OPT_SORT_KEYS)


def loads(data: bytes | str):
    if isinstance(data, str):
        data = data.encode()
    return orjson.loads(data)