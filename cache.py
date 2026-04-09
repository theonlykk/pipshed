"""
cache.py — Redis with in-process dict fallback.
If REDIS_URL is not set, everything runs in-memory (single-process only).
"""
import json
import os
import logging
import threading
import time

log = logging.getLogger(__name__)

_redis_client = None
_redis_lock = threading.Lock()
_mem: dict = {}      # fallback store: key → (value_str, expires_at or None)
_mem_lock = threading.Lock()


def get_redis():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    url = os.environ.get("REDIS_URL")
    if not url:
        return None
    with _redis_lock:
        if _redis_client is None:
            try:
                import redis
                _redis_client = redis.from_url(url, decode_responses=True)
                _redis_client.ping()
                log.info("Redis connected")
            except Exception as e:
                log.warning("Redis unavailable (%s), using in-memory fallback", e)
                _redis_client = None
    return _redis_client


def cache_key(*parts) -> str:
    return ":".join(str(p) for p in parts)


def cache_set(key: str, value, ex: int = 300):
    blob = json.dumps(value)
    ttl = int(ex) if ex is not None else 0
    if ttl < 0:
        ttl = 0
    expires_at = time.monotonic() + ttl if ttl else None
    r = get_redis()
    if r is not None:
        try:
            if ttl > 0:
                r.set(key, blob, ex=ttl)
            else:
                r.set(key, blob)
            with _mem_lock:
                _mem[key] = (blob, expires_at)
            return
        except Exception as e:
            log.warning("Redis set failed: %s", e)
    with _mem_lock:
        _mem[key] = (blob, expires_at)


def _mem_get(key: str):
    with _mem_lock:
        entry = _mem.get(key)
    if entry is None:
        return None
    blob, expires_at = entry
    if expires_at is not None and time.monotonic() > expires_at:
        with _mem_lock:
            _mem.pop(key, None)
        return None
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        log.warning("Memory cache bad JSON for %s", key)
        with _mem_lock:
            _mem.pop(key, None)
        return None


def cache_get(key: str):
    """
    Read-through: try Redis first, then in-process memory.
    Previously Redis-only return on miss ignored _mem, so a value written to
    memory during a Redis SET failure (or dual-write) could never be read.
    """
    r = get_redis()
    if r is not None:
        try:
            raw = r.get(key)
            if raw is not None and raw != "":
                try:
                    val = json.loads(raw)
                    return val
                except json.JSONDecodeError:
                    log.warning("Redis GET bad JSON for %s", key)
        except Exception as e:
            log.warning("Redis get failed: %s", e)

    val = _mem_get(key)
    return val


def cache_delete(key: str):
    r = get_redis()
    if r is not None:
        try:
            r.delete(key)
        except Exception as e:
            log.warning("Redis delete failed: %s", e)
    with _mem_lock:
        _mem.pop(key, None)


def cache_has(key: str) -> bool:
    """True if key exists and (for memory) is not expired — without loading large values."""
    r = get_redis()
    if r is not None:
        try:
            if r.exists(key):
                return True
        except Exception as e:
            log.warning("Redis exists failed: %s", e)
    with _mem_lock:
        entry = _mem.get(key)
    if entry is None:
        return False
    _, expires_at = entry
    if expires_at is not None and time.monotonic() > expires_at:
        return False
    return True


def flush_chart_cache_keys() -> dict:
    """
    Remove every key prefixed chart_img: or chart: from Redis and the in-memory store.
    Used by GET /admin/flush_cache for development / clearing stale chart payloads.
    """
    redis_deleted = 0
    mem_deleted = 0
    r = get_redis()
    if r is not None:
        for pattern in ("chart_img:*", "chart:*"):
            try:
                for key in r.scan_iter(match=pattern, count=500):
                    try:
                        r.delete(key)
                        redis_deleted += 1
                    except Exception as e:
                        log.warning("Redis delete %s failed: %s", key, e)
            except Exception as e:
                log.warning("Redis scan_iter %s failed: %s", pattern, e)
    with _mem_lock:
        for k in list(_mem.keys()):
            if k.startswith("chart_img:") or k.startswith("chart:"):
                _mem.pop(k, None)
                mem_deleted += 1
    return {"redis_deleted": redis_deleted, "memory_deleted": mem_deleted}

