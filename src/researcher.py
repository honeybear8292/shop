import anthropic
from rich.console import Console
from .config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from .cache import cached

console = Console()

_RESEARCH_PROMPT = """\
한국 소규모 온라인 쇼핑몰 창업을 준비 중입니다. 아래 카테고리에서 판매하기 좋은 상품을 분석해주세요.
조건: 부피가 작고 가볍고, 식품·의약품처럼 법령이 복잡하지 않은 품목 위주.

카테고리: {category}

다음 형식으로 분석해주세요 (한국어):

## 1. 지금 잘 팔리는 상품 TOP 10
각 상품마다:
- 상품명 (구체적으로)
- 인기 이유 / 트렌드 배경
- 한국 소비자가 (예상 판매가)
- 경쟁 강도: 낮음 / 보통 / 높음

## 2. 틈새시장 기회 (경쟁 낮고 수요 있는 것)
3~5개 상품, 각각 한 줄 이유 포함

## 3. 유사 쇼핑몰 트렌드
국내 소규모 셀러들이 이 카테고리에서 주로 다루는 상품과 최근 흐름

## 4. 처음 창업자 추천 상품 구성
- 입문용 5~7개 상품 조합 제안
- 예상 초기 재고 비용 (대략적으로)
- 주의사항

최신 시장 데이터를 반영해 구체적으로 답변해주세요.\
"""


@cached("research", ttl_hours=24 * 7)  # trends shift slowly; week-long cache
def research_trending_products(category: str) -> str:
    """Return Claude's trend analysis for the given category (Korean)."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = _RESEARCH_PROMPT.format(category=category)

    console.print("[yellow]트렌드 분석 중 (웹 검색 포함)...[/yellow]")

    # web_search_20250305 is a server-side tool; no client-side execution needed.
    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            tools=[{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 5,
            }],
            messages=[{"role": "user", "content": prompt}],
        )
    except (anthropic.BadRequestError, anthropic.APIStatusError):
        # Fallback when web search tool is unavailable for this model/region
        console.print("[dim]웹 검색 미지원 → 기본 모드로 전환[/dim]")
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )

    return _extract_text(response)


def _extract_text(response) -> str:
    parts = []
    for block in response.content:
        if hasattr(block, "text"):
            parts.append(block.text)
    return "\n".join(parts).strip()
