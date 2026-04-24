"""Live exchange rates with multi-backend fallback (no API key required)."""
from __future__ import annotations

import time
import requests
from rich.console import Console

console = Console()

# Primary and secondary endpoints, tried in order.
_BACKENDS = [
    "https://open.er-api.com/v6/latest/{base}",
    "https://api.frankfurter.app/latest?from={base}",
]

_CACHE_TTL_SECS = 60 * 60 * 6  # 6 hours — rates move slowly

# Fallback rates (approximate, 2026 Q1) used when all APIs are unreachable.
_FALLBACK = {
    "USD": {"KRW": 1380.0, "CNY": 7.25, "EUR": 0.92, "JPY": 155.0},
    "CNY": {"KRW": 190.0, "USD": 0.138, "EUR": 0.127},
    "EUR": {"KRW": 1500.0, "USD": 1.09},
}

_cache: dict[str, tuple[float, dict]] = {}
_api_warned = False  # avoid spamming the same failure message


def _parse_rates(data: dict) -> dict | None:
    """Extract rate mapping from either supported backend's JSON."""
    if data.get("result") == "success" and "rates" in data:
        return data["rates"]  # open.er-api format
    if "rates" in data and "base" in data:
        return data["rates"]  # frankfurter format
    return None


def _fetch_rates(base: str) -> dict[str, float]:
    global _api_warned
    now = time.time()
    cached = _cache.get(base)
    if cached and now - cached[0] < _CACHE_TTL_SECS:
        return cached[1]

    for url_tmpl in _BACKENDS:
        try:
            resp = requests.get(url_tmpl.format(base=base), timeout=5)
            resp.raise_for_status()
            rates = _parse_rates(resp.json())
            if rates:
                _cache[base] = (now, rates)
                return rates
        except Exception:
            continue

    if not _api_warned:
        console.print("[yellow]환율 API 접근 불가 → 고정 환율 사용[/yellow]")
        _api_warned = True
    fallback = _FALLBACK.get(base, {})
    # Cache fallback too, so we don't keep retrying within the same session.
    _cache[base] = (now, fallback)
    return fallback


def convert(amount: float, from_cur: str, to_cur: str) -> float:
    """Convert an amount between currencies. Case-insensitive."""
    from_cur, to_cur = from_cur.upper(), to_cur.upper()
    if from_cur == to_cur:
        return amount
    rates = _fetch_rates(from_cur)
    rate = rates.get(to_cur)
    if rate is None:
        raise ValueError(f"환율 정보 없음: {from_cur} → {to_cur}")
    return amount * rate


def to_krw(amount: float, currency: str) -> int:
    """Convert to KRW and round to nearest won."""
    return round(convert(amount, currency, "KRW"))


def current_rates() -> dict[str, float]:
    """Snapshot of commonly-needed rates for display."""
    try:
        usd = _fetch_rates("USD")
        return {
            "USD_KRW": usd.get("KRW", 1380.0),
            "CNY_KRW": usd.get("KRW", 1380.0) / usd.get("CNY", 7.25),
        }
    except Exception:
        return {"USD_KRW": 1380.0, "CNY_KRW": 190.0}
