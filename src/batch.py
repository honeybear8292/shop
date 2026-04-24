"""Batch processing: read a CSV of candidate products, enrich each with
Naver price stats / overseas overview / margin / score, and emit a result CSV.

Input CSV (UTF-8 BOM ok):
    keyword                                (필수)
    sourcing_price, currency               (선택, 마진 계산용)
    target_margin                          (선택, 권장 판매가 산출용)

Optional cols are detected case-insensitively. Extra columns are preserved
in the output.

Output CSV adds:
    naver_count, naver_min, naver_median, naver_mean, naver_max,
    competition_level, competitor_malls, total_search_results,
    break_even_price, recommended_price, score_total, score_verdict
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from rich.console import Console
from rich.table import Table
from rich import box

from .price_finder import search_naver_shopping, naver_competition
from .margin import (
    PLATFORM_FEES,
    analyze,
    break_even_price,
    recommended_prices,
)
from .scorer import calculate_score

console = Console()

REQUIRED_COL = "keyword"
OPTIONAL_COLS = ("sourcing_price", "currency", "target_margin")
OUT_COLS = (
    "naver_count", "naver_min", "naver_median", "naver_mean", "naver_max",
    "competition_level", "competitor_malls", "total_search_results",
    "break_even_price", "recommended_price",
    "score_total", "score_verdict",
)


def _normalize_keys(row: dict) -> dict:
    """Lowercase + strip column names to make matching robust."""
    return {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = [_normalize_keys(r) for r in reader]
    if not rows:
        return []
    if REQUIRED_COL not in rows[0]:
        raise ValueError(
            f"CSV에 '{REQUIRED_COL}' 컬럼이 필요합니다. "
            f"발견된 컬럼: {list(rows[0].keys())}"
        )
    return [r for r in rows if r.get(REQUIRED_COL)]


def _to_float(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _stats(items: list[dict]) -> dict:
    prices = [i["price"] for i in items if i.get("price")]
    if not prices:
        return {}
    from statistics import mean, median
    return {
        "count": len(prices),
        "min": min(prices),
        "median": int(median(prices)),
        "mean": int(mean(prices)),
        "max": max(prices),
    }


def process_row(
    row: dict,
    platform: str = "smartstore",
    intl_shipping: int = 3000,
    domestic_shipping: int = 3000,
    origin: str = "CN",
    default_target_margin: float = 0.3,
) -> dict:
    keyword = row[REQUIRED_COL]
    sourcing = _to_float(row.get("sourcing_price"))
    currency = (row.get("currency") or "USD").upper()
    target_margin = _to_float(row.get("target_margin")) or default_target_margin

    items = search_naver_shopping(keyword, display=30)
    stats = _stats(items)
    comp = naver_competition(items)

    out: dict = dict(row)
    out["naver_count"] = stats.get("count", 0)
    out["naver_min"] = stats.get("min", "")
    out["naver_median"] = stats.get("median", "")
    out["naver_mean"] = stats.get("mean", "")
    out["naver_max"] = stats.get("max", "")
    out["competition_level"] = comp.get("level", "")
    out["competitor_malls"] = comp.get("unique_malls", "")
    out["total_search_results"] = comp.get("total_results", "")

    margin_rate: float | None = None
    if sourcing is not None:
        bep = break_even_price(
            sourcing, currency, platform,
            intl_shipping_krw=intl_shipping,
            domestic_shipping_krw=domestic_shipping,
            origin=origin,
        )
        recs = recommended_prices(
            sourcing, currency, platform,
            target_margins=(target_margin,),
            intl_shipping_krw=intl_shipping,
            domestic_shipping_krw=domestic_shipping,
            origin=origin,
        )
        rec_price = recs.get(target_margin)
        out["break_even_price"] = bep
        out["recommended_price"] = rec_price or ""

        # If naver median is available, estimate actual margin assuming
        # we sell at naver median (realistic price benchmark)
        if stats.get("median") and rec_price:
            actual = analyze(
                sourcing, currency, stats["median"], platform,
                intl_shipping, domestic_shipping, origin,
            )
            margin_rate = actual.margin_rate
    else:
        out["break_even_price"] = ""
        out["recommended_price"] = ""

    score = calculate_score(
        margin_rate=margin_rate,
        competition=comp,
        naver_stats=stats,
    )
    out["score_total"] = score.total
    out["score_verdict"] = score.verdict

    return out


def run_batch(
    input_path: Path,
    output_path: Path | None = None,
    platform: str = "smartstore",
    intl_shipping: int = 3000,
    domestic_shipping: int = 3000,
    origin: str = "CN",
    default_target_margin: float = 0.3,
) -> Path:
    rows = _read_csv(input_path)
    if not rows:
        console.print("[red]입력 CSV가 비어있습니다[/red]")
        raise SystemExit(1)

    console.print(f"[cyan]총 {len(rows)}개 상품 처리 시작[/cyan]")
    enriched: list[dict] = []
    for i, row in enumerate(rows, 1):
        console.print(f"  [dim]({i}/{len(rows)})[/dim] {row[REQUIRED_COL]}")
        try:
            enriched.append(process_row(
                row, platform=platform,
                intl_shipping=intl_shipping,
                domestic_shipping=domestic_shipping,
                origin=origin,
                default_target_margin=default_target_margin,
            ))
        except Exception as exc:
            console.print(f"    [red]실패: {exc}[/red]")
            err_row = dict(row)
            err_row["score_verdict"] = f"오류: {exc}"
            enriched.append(err_row)

    if output_path is None:
        output_path = input_path.with_name(f"{input_path.stem}_enriched.csv")

    # Sort: highest score first
    enriched.sort(
        key=lambda r: float(r.get("score_total") or 0),
        reverse=True,
    )

    # Determine output columns: input cols first, then enrichment cols
    input_cols = list(rows[0].keys())
    out_cols = input_cols + [c for c in OUT_COLS if c not in input_cols]

    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=out_cols, extrasaction="ignore")
        writer.writeheader()
        for r in enriched:
            writer.writerow(r)

    console.print(f"[green]✓ 저장 완료: {output_path}[/green]")
    _print_summary(enriched)
    return output_path


def _print_summary(rows: Iterable[dict]) -> None:
    t = Table(
        title="[bold]일괄 처리 요약 (점수 순)[/bold]",
        box=box.ROUNDED,
    )
    t.add_column("#", style="dim", justify="right")
    t.add_column("키워드", style="cyan")
    t.add_column("점수", justify="right")
    t.add_column("판정")
    t.add_column("경쟁", justify="center")
    t.add_column("권장가", justify="right")

    color_map = {
        "강력 추천": "bold green",
        "추천": "green",
        "보통": "yellow",
        "재고려": "orange1",
        "비추": "red",
    }

    for i, r in enumerate(rows, 1):
        verdict = r.get("score_verdict", "")
        color = color_map.get(verdict, "white")
        rec = r.get("recommended_price", "")
        rec_str = f"{int(rec):,}원" if rec else "-"
        t.add_row(
            str(i),
            r.get(REQUIRED_COL, ""),
            f"{r.get('score_total', '-')}",
            f"[{color}]{verdict}[/{color}]",
            r.get("competition_level", "-"),
            rec_str,
        )

    console.print(t)
