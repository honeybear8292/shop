import re
from statistics import mean, median, pstdev

import requests
import anthropic
from rich.console import Console
from rich.table import Table
from rich import box
from .config import ANTHROPIC_API_KEY, NAVER_CLIENT_ID, NAVER_CLIENT_SECRET, CLAUDE_MODEL
from .exchange import current_rates
from .cache import cached
from .translator import translate_product_name

console = Console()

_OVERSEAS_PROMPT = """\
아래 상품의 중국 사이트 최저 구매 가격을 검색해서 정리해주세요.

상품 (한국어): {ko}
영어 검색어 (AliExpress용): {en}
중국어 검색어 (1688용): {zh}

참고 환율 (오늘 기준):
- USD 1 = KRW {usd_krw:,.0f}
- CNY 1 = KRW {cny_krw:,.0f}

다음 사이트별 최저가를 찾아주세요. **각 사이트에 맞는 언어 검색어를 사용하세요**:
1. AliExpress (aliexpress.com) — 영어 검색어 사용, 소매 단위
2. 1688.com — 중국어 검색어 사용, 도매 단위 (CNY)
3. Alibaba.com — 영어 검색어, 대량 구매 가격 (있으면)

아래 형식으로 답변 (한국어). 원화 환산 시 반드시 위 환율 사용:

## AliExpress 최저가
- 가격: USD X.XX (약 KRW X,XXX)
- 사용한 검색어
- 주요 판매 국가/브랜드

## 1688 최저가 (도매)
- 가격: CNY X (약 KRW X,XXX)
- 최소 구매 수량 (MOQ)
- 사용한 검색어

## Alibaba 대량 구매
- 가격대 범위 (있으면)
- 최소 주문 수량

## 한국 판매가 대비 마진 분석
- AliExpress 기준 예상 마진율 (쿠팡 ~10%, 스마트스토어 ~3.7% 감안)
- 1688 기준 예상 마진율

## 구매 팁
- 추천 플랫폼과 이유
- 주의사항 (배송비, 관세(150 USD 초과 시), 품질 편차 등)\
"""


# ── Naver Shopping ──────────────────────────────────────────────────────────

@cached("naver", ttl_hours=24)
def search_naver_shopping(query: str, display: int = 10) -> list[dict]:
    """Call Naver Shopping Search API. Returns [] when credentials are absent.

    Cached for 24h per (query, display) tuple.
    """
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        return []

    url = "https://openapi.naver.com/v1/search/shop.json"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }
    params = {"query": query, "display": display, "sort": "sim"}

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        console.print(f"[red]네이버 API 오류: {exc}[/red]")
        return []

    items = []
    for item in data.get("items", []):
        title = re.sub(r"<[^>]+>", "", item.get("title", ""))
        lprice = int(item.get("lprice") or 0)
        if lprice == 0:
            continue
        items.append({
            "title": title,
            "price": lprice,
            "mall": item.get("mallName", ""),
            "link": item.get("link", ""),
            "brand": item.get("brand", ""),
            "category": item.get("category1", ""),
            "source": "naver",
        })

    items.sort(key=lambda x: x["price"])
    # Attach total result count from API (used for competitor analysis)
    if items:
        items[0].setdefault("_total_results", int(data.get("total", 0)))
    return items


# ── Overseas (AliExpress / 1688 via Claude web search) ──────────────────────

@cached("overseas", ttl_hours=24)
def _claude_overseas_call(ko: str, en: str, zh: str, usd_krw: float, cny_krw: float) -> str:
    """Pure Claude call, cached. Inputs determine cache key."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = _OVERSEAS_PROMPT.format(
        ko=ko, en=en, zh=zh,
        usd_krw=usd_krw, cny_krw=cny_krw,
    )
    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2048,
            tools=[{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 5,
            }],
            messages=[{"role": "user", "content": prompt}],
        )
    except (anthropic.BadRequestError, anthropic.APIStatusError):
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
    parts = [block.text for block in response.content if hasattr(block, "text")]
    return "\n".join(parts).strip()


def search_overseas_prices(product: str) -> str:
    """Translate product name then query Claude for overseas prices (cached)."""
    console.print("[yellow]상품명 번역 중 (다국어)...[/yellow]")
    names = translate_product_name(product)
    console.print(
        f"  [dim]EN:[/dim] {names['en']}    [dim]ZH:[/dim] {names['zh']}"
    )

    rates = current_rates()
    console.print("[yellow]해외 구매처 검색 중 (AliExpress / 1688)...[/yellow]")
    return _claude_overseas_call(
        names["ko"], names["en"], names["zh"],
        round(rates["USD_KRW"], 2),
        round(rates["CNY_KRW"], 2),
    )


# ── Naver competitor analysis ────────────────────────────────────────────────

def naver_competition(items: list[dict]) -> dict:
    """Estimate competition level from Naver Shopping results."""
    if not items:
        return {"level": "데이터 없음", "score": 0, "details": {}}

    prices = [i["price"] for i in items]
    malls = [i.get("mall", "") for i in items if i.get("mall")]
    unique_malls = len(set(malls))
    total_results = items[0].get("_total_results", len(items))

    # Mall concentration (HHI-style): top 3 malls share of returned items
    from collections import Counter
    counter = Counter(malls)
    top3_share = sum(c for _, c in counter.most_common(3)) / len(malls) if malls else 0

    # Price spread (coefficient of variation)
    cv = pstdev(prices) / mean(prices) if len(prices) > 1 and mean(prices) else 0

    # Competition heuristic
    # - <10 unique malls AND <100 results = 낮음
    # - 10-30 unique AND 100-1000 results = 보통
    # - >30 unique OR >1000 results = 높음
    if unique_malls < 10 and total_results < 100:
        level = "낮음"
    elif unique_malls > 30 or total_results > 1000:
        level = "높음"
    else:
        level = "보통"

    return {
        "level": level,
        "unique_malls": unique_malls,
        "total_results": total_results,
        "top3_concentration": round(top3_share, 2),
        "price_cv": round(cv, 3),
    }


# ── Aggregator ───────────────────────────────────────────────────────────────

def _naver_stats(items: list[dict]) -> dict | None:
    prices = [i["price"] for i in items if i.get("price")]
    if not prices:
        return None
    return {
        "min": min(prices),
        "median": int(median(prices)),
        "mean": int(mean(prices)),
        "max": max(prices),
        "count": len(prices),
    }


def find_all_prices(product: str) -> dict:
    """Collect prices from Naver Shopping and overseas platforms."""
    console.print(f"\n[cyan]'{product}' 가격 조회 시작[/cyan]")
    result: dict = {
        "product": product,
        "naver": [],
        "overseas": "",
        "stats": None,
        "competition": None,
    }

    if NAVER_CLIENT_ID:
        console.print("[yellow]네이버 쇼핑 검색 중...[/yellow]")
        result["naver"] = search_naver_shopping(product, display=30)
        result["stats"] = _naver_stats(result["naver"])
        result["competition"] = naver_competition(result["naver"])
    else:
        console.print("[dim]네이버 API 키 없음 → 건너뜀[/dim]")

    result["overseas"] = search_overseas_prices(product)
    return result


# ── Rich tables ──────────────────────────────────────────────────────────────

def build_naver_table(items: list[dict], product: str) -> Table:
    table = Table(
        title=f"[bold]네이버 쇼핑: {product}[/bold]",
        box=box.ROUNDED,
        show_lines=False,
    )
    table.add_column("상품명", style="cyan", max_width=42, no_wrap=False)
    table.add_column("최저가", style="green", justify="right")
    table.add_column("쇼핑몰", style="yellow")

    for item in items[:8]:
        table.add_row(
            item["title"][:42],
            f"{item['price']:,}원",
            item["mall"],
        )
    return table


def build_stats_table(stats: dict) -> Table:
    t = Table(title="[bold]네이버 가격대 통계[/bold]", box=box.ROUNDED)
    t.add_column("지표", style="cyan")
    t.add_column("값", style="green", justify="right")
    t.add_row("검색 결과 수", f"{stats['count']}개")
    t.add_row("최저가", f"{stats['min']:,}원")
    t.add_row("중앙값", f"{stats['median']:,}원")
    t.add_row("평균가", f"{stats['mean']:,}원")
    t.add_row("최고가", f"{stats['max']:,}원")
    return t


def build_competition_table(comp: dict) -> Table:
    color = {"낮음": "green", "보통": "yellow", "높음": "red"}.get(comp["level"], "white")
    t = Table(title="[bold]경쟁 강도 분석[/bold]", box=box.ROUNDED)
    t.add_column("지표", style="cyan")
    t.add_column("값", justify="right")
    t.add_row("경쟁 강도", f"[{color}]{comp['level']}[/{color}]")
    t.add_row("전체 검색 결과", f"{comp.get('total_results', 0):,}건")
    t.add_row("판매 쇼핑몰 수 (샘플)", f"{comp.get('unique_malls', 0)}개")
    t.add_row(
        "상위 3몰 점유율",
        f"{comp.get('top3_concentration', 0)*100:.0f}%",
    )
    t.add_row("가격 변동 계수", f"{comp.get('price_cv', 0):.2f}")
    return t
