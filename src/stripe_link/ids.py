"""
Snowflake -> Base62 ID generation.

Local document IDs stay stable even when names, titles, or slugs change.
Use generate_local_id() for product_id, price_id, page_id, offer_id, and other
application-owned IDs that may later sync to Stripe or other external systems.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time


ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
EPOCH = 1735689600000  # 2025-01-01T00:00:00Z in milliseconds

_lock = threading.Lock()
_last_ms = 0
_seq = 0


def to_base62(value: int) -> str:
    if value == 0:
        return "0"

    base = len(ALPHABET)
    result: list[str] = []
    while value > 0:
        result.append(ALPHABET[value % base])
        value //= base
    return "".join(reversed(result))


def _get_dynamic_worker_id(context: object | None = None) -> int:
    aws_request_id = getattr(context, "aws_request_id", None)
    if aws_request_id:
        hasher = hashlib.md5(str(aws_request_id).encode("utf-8"), usedforsecurity=False)
        return int(hasher.hexdigest(), 16) & 0x3FF

    worker_env = os.getenv("WORKER_ID")
    if worker_env is not None:
        try:
            return int(worker_env) & 0x3FF
        except ValueError:
            pass

    return 1


def generate_id(context: object | None = None) -> str:
    global _last_ms, _seq

    worker_id = _get_dynamic_worker_id(context)
    with _lock:
        now = int(time.time() * 1000)

        if now < _last_ms:
            time_drift = _last_ms - now
            if time_drift < 50:
                while now < _last_ms:
                    now = int(time.time() * 1000)
            else:
                raise RuntimeError(f"Clock moved backwards. Rejecting ID generation for {time_drift}ms.")

        if now == _last_ms:
            _seq = (_seq + 1) & 0x1FFF
            if _seq == 0:
                while now <= _last_ms:
                    now = int(time.time() * 1000)
        else:
            _seq = 0

        _last_ms = now
        time_part = (now - EPOCH) & 0x1FFFFFFFFFF
        value = (time_part << 23) | (worker_id << 13) | _seq
        return to_base62(value).zfill(11)


def generate_local_id(context: object | None = None) -> str:
    return f"local_{generate_id(context)}"


def generate_short_url_code(context: object | None = None) -> str:
    return generate_id(context)
