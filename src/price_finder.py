import re
from statistics import mean, median

import requests
import anthropic
from rich.console import Console
from rich.table import Table
from rich import box
from .config import ANTHROPIC_API_KEY, NAVER_CLIENT_ID, NAVER_CLIENT_SECRET, CLAUDE_MODEL
from .exchange import current_rates

console = Console()

_OVERSEAS_PROMPT = """\
아래 상품의 중국 사이트 최저 구매 가격을 검색해서 정리해주세요.

상품: {product}

참고 환율 (오늘 기준):
- USD 1 = KRW {usd_krw:,.0f}
- CNY 1 = KRW {cny_krw:,.0f}

다음 사이트별 최저가를 찾아주세요:
1. AliExpress (aliexpress.com) — 소매 단위
2. 1688.com — 도매 단위 (CNY 기준)
3. Alibaba.com — 대량 구매 가격 (있으면)

아래 형식으로 답변 (한국어). 원화 환산 시 반드시 위 환율 사용:

## AliExpress 최저가
- 가격: USD X.XX (약 KRW X,XXX)
- 대표 검색어 또는 상품 특징
- 주요 판매 국가/브랜드

## 1688 최저가 (도매)
- 가격: CNY X (약 KRW X,XXX)
- 최소 구매 수량 (MOQ)
- 대표 검색어

## Alibaba 대량 구매
- 가격대 범위 (있으면)
- 최소 주문 수량

## 한국 판매가 대비 마진 분석
- AliExpress 기준 예상 마진율 (쿠팡 수수료 ~10%, 스마트스토어 ~3.7% 감안)
- 1688 기준 예상 마진율

## 구매 팁
- 추천 플랫폼과 이유
- 주의사항 (배송비, 관세(150 USD 초과 시), 품질 편차 등)\
"""


# ── Naver Shopping ──────────────────────────────────────────────────────────

def search_naver_shopping(query: str, display: int = 10) -> list[dict]:
    """Call Naver Shopping Search API. Returns [] when credentials are absent."""
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
            "source": "naver",
        })

    return sorted(items, key=lambda x: x["price"])


# ── Overseas (AliExpress / 1688 via Claude web search) ──────────────────────

def search_overseas_prices(product: str) -> str:
    """Use Claude + web_search to find overseas prices."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    rates = current_rates()
    prompt = _OVERSEAS_PROMPT.format(
        product=product,
        usd_krw=rates["USD_KRW"],
        cny_krw=rates["CNY_KRW"],
    )

    console.print("[yellow]해외 구매처 검색 중 (AliExpress / 1688)...[/yellow]")

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
        console.print("[dim]웹 검색 미지원 → 기본 모드로 전환[/dim]")
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )

    parts = [block.text for block in response.content if hasattr(block, "text")]
    return "\n".join(parts).strip()


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
    result: dict = {"product": product, "naver": [], "overseas": "", "stats": None}

    if NAVER_CLIENT_ID:
        console.print("[yellow]네이버 쇼핑 검색 중...[/yellow]")
        result["naver"] = search_naver_shopping(product, display=30)
        result["stats"] = _naver_stats(result["naver"])
    else:
        console.print("[dim]네이버 API 키 없음 → 건너뜀[/dim]")

    result["overseas"] = search_overseas_prices(product)
    return result


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
