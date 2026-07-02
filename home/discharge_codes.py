import random
import time

from django.core.cache import cache


CODE_TTL_SECONDS = 30
_CACHE_KEY_PREFIX = "discharge_code:"


def _cache_key(visit_id):
    return f"{_CACHE_KEY_PREFIX}{visit_id}"


def get_or_create_discharge_code(visit_id):
    """
    Return a 5-digit code for a visit, reusing active code for 30 seconds.
    """
    key = _cache_key(visit_id)
    payload = cache.get(key)
    if payload and isinstance(payload, dict):
        code = payload.get("code")
        expires_at = int(payload.get("expires_at", 0))
        if code and expires_at > int(time.time()):
            return code

    code = f"{random.randint(10000, 99999)}"
    expires_at = int(time.time()) + CODE_TTL_SECONDS
    cache.set(
        key,
        {"code": code, "expires_at": expires_at},
        timeout=CODE_TTL_SECONDS,
    )
    return code


def get_or_create_discharge_code_payload(visit_id):
    """
    Return active code and its remaining seconds.
    """
    key = _cache_key(visit_id)
    now = int(time.time())
    payload = cache.get(key)

    if not payload or not isinstance(payload, dict):
        code = f"{random.randint(10000, 99999)}"
        expires_at = now + CODE_TTL_SECONDS
        payload = {"code": code, "expires_at": expires_at}
        cache.set(key, payload, timeout=CODE_TTL_SECONDS)
    else:
        code = payload.get("code")
        expires_at = int(payload.get("expires_at", 0))
        if not code or expires_at <= now:
            code = f"{random.randint(10000, 99999)}"
            expires_at = now + CODE_TTL_SECONDS
            payload = {"code": code, "expires_at": expires_at}
            cache.set(key, payload, timeout=CODE_TTL_SECONDS)

    remaining_seconds = max(0, int(payload["expires_at"]) - now)
    return {
        "code": payload["code"],
        "expires_at": int(payload["expires_at"]),
        "remaining_seconds": remaining_seconds,
        "ttl_seconds": CODE_TTL_SECONDS,
    }


def validate_discharge_code(visit_id, submitted_code):
    """
    Validate submitted code against active 30-second visit code.
    """
    if not submitted_code:
        return False
    payload = cache.get(_cache_key(visit_id))
    if not payload or not isinstance(payload, dict):
        return False
    if int(payload.get("expires_at", 0)) <= int(time.time()):
        return False
    return str(submitted_code).strip() == str(payload.get("code", "")).strip()
