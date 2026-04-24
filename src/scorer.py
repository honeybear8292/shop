"""Aggregate market signals into a single 0–10 'sales suitability' score.

Components (each 0–10):
  - margin:       마진율이 높을수록 높음
  - competition:  경쟁 강도가 낮을수록 높음
  - stability:    가격대가 안정적일수록 높음 (가격 변동 계수 기반)
  - demand:       검색 결과 수가 적당할수록 높음 (너무 적으면 무수요, 너무 많으면 레드오션)

A weighted average produces the final score. Returns a structured dict
suitable for both display and CSV export.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from math import log10

from rich.table import Table
from rich import box


@dataclass
class ScoreBreakdown:
    total: float
    margin: float
    competition: float
    stability: float
    demand: float
    verdict: str  # "강력 추천" / "추천" / "보통" / "비추" / "재고려"


def _verdict(total: float) -> str:
    if total >= 8.0:
        return "강력 추천"
    if total >= 6.5:
        return "추천"
    if total >= 5.0:
        return "보통"
    if total >= 3.5:
        return "재고려"
    return "비추"


def _margin_score(margin_rate: float | None) -> float:
    """0% → 0점, 30% → 10점, 50%+ → 10점."""
    if margin_rate is None:
        return 5.0  # 데이터 없음 → 중립
    return max(0.0, min(10.0, margin_rate * 100 / 3))


def _competition_score(comp: dict | None) -> float:
    """낮음=9, 보통=6, 높음=3 + 상위3몰 점유율 보정."""
    if not comp:
        return 5.0
    base = {"낮음": 9.0, "보통": 6.0, "높음": 3.0}.get(comp.get("level"), 5.0)
    # 상위 3몰이 80%+ 점유 → 진입 어려움 (보정 -1)
    top3 = comp.get("top3_concentration", 0)
    if top3 > 0.8:
        base -= 1.0
    elif top3 < 0.3:
        base += 0.5  # 분산된 시장은 진입 수월
    return max(0.0, min(10.0, base))


def _stability_score(price_cv: float | None) -> float:
    """CV 0~0.2 → 9~10점, 1.0+ → 0점."""
    if price_cv is None:
        return 5.0
    if price_cv < 0.2:
        return 10.0
    return max(0.0, min(10.0, 10 - (price_cv - 0.2) * 12.5))


def _demand_score(total_results: int | None) -> float:
    """검색 결과 수: 100~5000 = 골디락스 (8~10), 너무 적거나 많으면 감점."""
    if not total_results:
        return 0.0
    n = total_results
    if n < 10:
        return 1.0
    if n < 100:
        return 4.0 + (n - 10) / 30  # 4.0 ~ 7.0
    if n < 1000:
        return 8.0 + log10(n / 100)  # 8.0 ~ 9.0
    if n < 10000:
        return 9.0 - (n - 1000) / 4500  # 9.0 ~ 7.0
    return max(2.0, 7.0 - log10(n / 10000))  # 7.0 →


def calculate_score(
    margin_rate: float | None = None,
    competition: dict | None = None,
    naver_stats: dict | None = None,
) -> ScoreBreakdown:
    """Compute composite suitability score from price/competition signals."""
    # 시장 데이터(네이버) 자체가 비어있으면 점수 산출 의미 없음
    has_market_data = competition and competition.get("level") != "데이터 없음"
    if not has_market_data and margin_rate is None:
        return ScoreBreakdown(
            total=0.0, margin=0.0, competition=0.0,
            stability=0.0, demand=0.0, verdict="데이터 부족",
        )

    margin = _margin_score(margin_rate)
    comp = _competition_score(competition)
    stab = _stability_score(competition.get("price_cv") if competition else None)
    demand = _demand_score(competition.get("total_results") if competition else None)

    # Weights: margin and competition matter most
    weights = {"margin": 0.35, "competition": 0.30, "stability": 0.15, "demand": 0.20}
    total = (
        margin * weights["margin"]
        + comp * weights["competition"]
        + stab * weights["stability"]
        + demand * weights["demand"]
    )

    return ScoreBreakdown(
        total=round(total, 1),
        margin=round(margin, 1),
        competition=round(comp, 1),
        stability=round(stab, 1),
        demand=round(demand, 1),
        verdict=_verdict(total),
    )


def render_score(score: ScoreBreakdown, product: str = "") -> Table:
    color = {
        "강력 추천": "bold green",
        "추천": "green",
        "보통": "yellow",
        "재고려": "orange1",
        "비추": "red",
    }.get(score.verdict, "white")

    title = f"[bold]판매 적합도 점수: {product}[/bold]" if product else "[bold]판매 적합도 점수[/bold]"
    t = Table(title=title, box=box.ROUNDED)
    t.add_column("항목", style="cyan")
    t.add_column("점수", justify="right")
    t.add_column("가중치", style="dim", justify="right")
    t.add_row("마진성", f"{score.margin:.1f} / 10", "35%")
    t.add_row("경쟁성", f"{score.competition:.1f} / 10", "30%")
    t.add_row("수요성", f"{score.demand:.1f} / 10", "20%")
    t.add_row("가격 안정성", f"{score.stability:.1f} / 10", "15%")
    t.add_section()
    t.add_row(
        f"[{color}]종합[/{color}]",
        f"[{color}]{score.total:.1f} / 10[/{color}]",
        "",
    )
    t.add_row(
        f"[{color}]판정[/{color}]",
        f"[{color}]{score.verdict}[/{color}]",
        "",
    )
    return t


def to_dict(score: ScoreBreakdown) -> dict:
    return asdict(score)
