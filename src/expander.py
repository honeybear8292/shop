"""Expand a broad category (e.g. '문구류') into concrete searchable keywords,
then probe Naver Shopping for price statistics per keyword."""
from __future__ import annotations

import json
import re
from statistics import mean, median

import anthropic
from rich.console import Console
from rich.table import Table
from rich import box

from .config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from .price_finder import search_naver_shopping

console = Console()

_EXPAND_PROMPT = """\
한국 소규모 쇼핑몰에서 판매할 '{category}' 관련 구체적 상품 검색 키워드를 {count}개 추천해주세요.

조건:
- 한국 온라인에서 실제 수요가 있을 만한 상품
- 부피·무게가 작아 개인 셀러가 다루기 쉬운 것
- 식품·의약품·전기전자처럼 법령 규제가 복잡한 품목 제외
- 모호한 표현(예: "예쁜 것") 말고 구체적 상품명 (예: "A5 하드커버 다이어리")

JSON 배열 형태로만 답변하세요. 설명·코드펜스 없이 배열만:
["키워드1", "키워드2", ...]\
"""


def expand_category(category: str, count: int = 10) -> list[str]:
    """Ask Claude for a list of concrete product keywords."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": _EXPAND_PROMPT.format(category=category, count=count),
        }],
    )
    text = resp.content[0].text.strip()
    text = _strip_code_fence(text)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Last-ditch: extract first JSON array substring
        m = re.search(r"\[.*\]", text, re.DOTALL)
        parsed = json.loads(m.group(0)) if m else []

    return [k.strip() for k in parsed if isinstance(k, str) and k.strip()]


def _strip_code_fence(text: str) -> str:
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith(("json", "JSON")):
            text = text[4:]
        # remove trailing fence residue
        text = text.rstrip("`").strip()
    return text


def price_stats(items: list[dict]) -> dict | None:
    """Compute min/median/mean/max from Naver search results."""
    prices = [i["price"] for i in items if i.get("price")]
    if not prices:
        return None
    return {
        "min": min(prices),
        "median": int(median(prices)),
        "mean": int(mean(prices)),
        "max": max(prices),
    }


def expand_with_prices(category: str, count: int = 10) -> list[dict]:
    """Expand + probe Naver Shopping per keyword. Returns rows with stats."""
    console.print(f"[yellow]'{category}' → {count}개 키워드 생성 중...[/yellow]")
    keywords = expand_category(category, count)
    if not keywords:
        console.print("[red]키워드 생성 실패[/red]")
        return []

    console.print(f"[green]{len(keywords)}개 키워드 확보 → 네이버 가격 조회[/green]")

    rows: list[dict] = []
    for i, kw in enumerate(keywords, 1):
        console.print(f"  [dim]({i}/{len(keywords)})[/dim] {kw}")
        items = search_naver_shopping(kw, display=20)
        rows.append({
            "keyword": kw,
            "count": len(items),
            "stats": price_stats(items),
            "top": items[:3],  # keep top 3 cheapest for reference
        })
    return rows


# ── Rich display ─────────────────────────────────────────────────────────────

def render_expansion(category: str, rows: list[dict]) -> Table:
    t = Table(
        title=f"[bold]{category} 키워드 확장 (네이버 가격대)[/bold]",
        box=box.ROUNDED,
    )
    t.add_column("#", style="dim", justify="right")
    t.add_column("키워드", style="cyan")
    t.add_column("결과", justify="right")
    t.add_column("최저가", style="green", justify="right")
    t.add_column("중앙가", style="yellow", justify="right")
    t.add_column("평균가", justify="right")
    t.add_column("최고가", justify="right")

    for i, r in enumerate(rows, 1):
        s = r.get("stats")
        if s:
            t.add_row(
                str(i),
                r["keyword"],
                str(r["count"]),
                f"{s['min']:,}원",
                f"{s['median']:,}원",
                f"{s['mean']:,}원",
                f"{s['max']:,}원",
            )
        else:
            t.add_row(str(i), r["keyword"], str(r["count"]), "-", "-", "-", "-")
    return t
