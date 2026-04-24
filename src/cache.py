"""File-based cache for API calls. Reduces repeat costs (Claude / Naver / etc).

Usage:
    @cached("naver", ttl_hours=24)
    def search_naver_shopping(query, display=10):
        ...

Cache files live under ./cache/<namespace>/<sha1>.json
A file's metadata (timestamp, args) is bundled with the value, so cache files
are self-describing.
"""
from __future__ import annotations

import functools
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

CACHE_DIR = Path("cache")


def _key(args: tuple, kwargs: dict) -> str:
    """Stable hash of positional + keyword arguments."""
    blob = json.dumps([args, kwargs], sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def _path(namespace: str, key: str) -> Path:
    d = CACHE_DIR / namespace
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}.json"


def load(namespace: str, key: str, ttl_hours: float) -> Any | None:
    p = _path(namespace, key)
    if not p.exists():
        return None
    try:
        record = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if time.time() - record.get("ts", 0) > ttl_hours * 3600:
        return None
    return record.get("value")


def store(namespace: str, key: str, value: Any, args_repr: str = "") -> None:
    p = _path(namespace, key)
    record = {"ts": time.time(), "args": args_repr[:200], "value": value}
    try:
        p.write_text(
            json.dumps(record, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except (TypeError, OSError):
        # Value not JSON-serializable; skip silently
        pass


def cached(namespace: str, ttl_hours: float = 24.0) -> Callable:
    """Decorator caching the function's return value as JSON."""
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            key = _key(args, kwargs)
            hit = load(namespace, key, ttl_hours)
            if hit is not None:
                return hit
            result = fn(*args, **kwargs)
            if result is not None:
                store(namespace, key, result, args_repr=repr((args, kwargs)))
            return result
        wrapper.__wrapped__ = fn  # allow bypass via fn.__wrapped__(...)
        return wrapper
    return decorator


def clear(namespace: str | None = None) -> int:
    """Remove cached files. Returns count deleted."""
    target = CACHE_DIR / namespace if namespace else CACHE_DIR
    if not target.exists():
        return 0
    count = 0
    for p in target.rglob("*.json"):
        p.unlink()
        count += 1
    return count


def stats() -> dict[str, int]:
    """Return {namespace: file_count}."""
    if not CACHE_DIR.exists():
        return {}
    return {
        ns.name: len(list(ns.glob("*.json")))
        for ns in CACHE_DIR.iterdir()
        if ns.is_dir()
    }
