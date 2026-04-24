"""Translate Korean product names to English (AliExpress) and Chinese (1688)."""
from __future__ import annotations

import json
import re

import anthropic

from .cache import cached
from .config import ANTHROPIC_API_KEY, CLAUDE_MODEL

_PROMPT = """\
한국어 상품명을 다른 언어 쇼핑 사이트 검색용으로 번역해주세요.

상품: {product}

요구사항:
- en: AliExpress(영어 검색용). 자연스러운 영어 검색 키워드 (예: "cat automatic water dispenser")
- zh: 1688(중국어 검색용). 중국 도매 사이트에서 실제 사용되는 제품명 (간체)
- 직역이 아니라 해당 사이트에서 실제로 잘 검색되는 키워드 형태
- 너무 길게 풀어쓰지 말고 검색에 효과적인 핵심 키워드만

JSON 형식으로만 답변. 다른 설명이나 코드펜스 없이:
{{"ko": "...", "en": "...", "zh": "..."}}\
"""


def _strip_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


@cached("translation", ttl_hours=24 * 30)  # translations rarely change
def translate_product_name(product: str) -> dict[str, str]:
    """Return {'ko': ..., 'en': ..., 'zh': ...}.

    Falls back to Korean for missing fields if Claude returns malformed JSON.
    """
    fallback = {"ko": product, "en": product, "zh": product}

    if not ANTHROPIC_API_KEY:
        return fallback

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    try:
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": _PROMPT.format(product=product)}],
        )
        text = _strip_fence(resp.content[0].text)
        # Extract first JSON object if wrapped in extra text
        m = re.search(r"\{.*\}", text, re.DOTALL)
        parsed = json.loads(m.group(0) if m else text)
    except Exception:
        return fallback

    return {
        "ko": parsed.get("ko") or product,
        "en": parsed.get("en") or product,
        "zh": parsed.get("zh") or product,
    }
