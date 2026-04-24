"""Persist research / price / expansion results to ./results as MD + JSON."""
from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path

RESULTS_DIR = Path("results")


def _timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H%M")


def _slugify(text: str, max_len: int = 40) -> str:
    """Filesystem-safe slug preserving Korean characters."""
    text = text.strip()
    # keep alnum, Korean (Hangul), space → underscore
    cleaned = re.sub(r"[^\w가-힣 \-]", "", text, flags=re.UNICODE)
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned[:max_len] or "untitled"


def _ensure_dir() -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    return RESULTS_DIR


# ── Research (trend analysis text) ───────────────────────────────────────────

def save_research(category: str, content: str) -> Path:
    d = _ensure_dir()
    path = d / f"{_timestamp()}_research_{_slugify(category)}.md"
    header = f"# {category} 트렌드 분석\n\n> {datetime.now():%Y-%m-%d %H:%M}\n\n"
    path.write_text(header + content, encoding="utf-8")
    return path


# ── Prices (Naver list + overseas markdown) ──────────────────────────────────

def save_prices(product: str, data: dict) -> tuple[Path, Path]:
    d = _ensure_dir()
    slug = _slugify(product)
    ts = _timestamp()

    json_path = d / f"{ts}_price_{slug}.json"
    md_path = d / f"{ts}_price_{slug}.md"

    json_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [f"# {product} 가격 조회", "", f"> {datetime.now():%Y-%m-%d %H:%M}", ""]

    naver = data.get("naver") or []
    if naver:
        lines.append("## 네이버 쇼핑 최저가")
        lines.append("")
        lines.append("| 순위 | 가격 | 상품명 | 쇼핑몰 |")
        lines.append("| --- | --- | --- | --- |")
        for i, item in enumerate(naver[:15], 1):
            title = item["title"].replace("|", "\\|")
            lines.append(
                f"| {i} | {item['price']:,}원 | {title[:50]} | {item.get('mall', '')} |"
            )
        if data.get("stats"):
            s = data["stats"]
            lines.append("")
            lines.append("### 가격 통계")
            lines.append(f"- 최저가: **{s['min']:,}원**")
            lines.append(f"- 중앙값: **{s['median']:,}원**")
            lines.append(f"- 평균가: **{s['mean']:,}원**")
            lines.append(f"- 최고가: **{s['max']:,}원**")
        if data.get("competition"):
            c = data["competition"]
            lines.append("")
            lines.append("### 경쟁 강도")
            lines.append(f"- 강도: **{c.get('level', '-')}**")
            lines.append(f"- 전체 검색 결과: {c.get('total_results', 0):,}건")
            lines.append(f"- 판매 쇼핑몰 수(샘플): {c.get('unique_malls', 0)}개")
            lines.append(f"- 상위 3몰 점유율: {c.get('top3_concentration', 0)*100:.0f}%")
        if data.get("score"):
            sc = data["score"]
            lines.append("")
            lines.append("### 판매 적합도 점수")
            lines.append(f"- **{sc.get('total')} / 10 — {sc.get('verdict')}**")
            lines.append(f"  - 마진성: {sc.get('margin')}")
            lines.append(f"  - 경쟁성: {sc.get('competition')}")
            lines.append(f"  - 수요성: {sc.get('demand')}")
            lines.append(f"  - 가격 안정성: {sc.get('stability')}")
        lines.append("")

    overseas = data.get("overseas") or ""
    if overseas:
        lines.append("## 해외 구매처 분석")
        lines.append("")
        lines.append(overseas)

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path, json_path


# ── Category expansion (keyword list + per-keyword price stats) ──────────────

def save_expansion(category: str, rows: list[dict]) -> tuple[Path, Path, Path]:
    """Save keyword expansion as MD, JSON, and CSV."""
    d = _ensure_dir()
    slug = _slugify(category)
    ts = _timestamp()

    md_path = d / f"{ts}_expand_{slug}.md"
    json_path = d / f"{ts}_expand_{slug}.json"
    csv_path = d / f"{ts}_expand_{slug}.csv"

    # JSON
    json_path.write_text(
        json.dumps({"category": category, "rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # CSV
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["키워드", "검색결과수", "최저가", "중앙가", "평균가", "최고가"]
        )
        for r in rows:
            s = r.get("stats") or {}
            writer.writerow([
                r["keyword"],
                r.get("count", 0),
                s.get("min", ""),
                s.get("median", ""),
                s.get("mean", ""),
                s.get("max", ""),
            ])

    # MD
    lines = [
        f"# {category} 키워드 확장",
        "",
        f"> {datetime.now():%Y-%m-%d %H:%M}",
        "",
        "| 키워드 | 결과 | 최저 | 중앙 | 평균 | 최고 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in rows:
        s = r.get("stats") or {}
        fmt = lambda v: f"{v:,}원" if isinstance(v, int) else "-"
        lines.append(
            f"| {r['keyword']} | {r.get('count', 0)} | {fmt(s.get('min'))} | "
            f"{fmt(s.get('median'))} | {fmt(s.get('mean'))} | {fmt(s.get('max'))} |"
        )
    md_path.write_text("\n".join(lines), encoding="utf-8")

    return md_path, json_path, csv_path
