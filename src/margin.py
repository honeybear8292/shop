"""Margin calculator for small shopping mall sellers.

Handles:
- Sourcing cost conversion (USD/CNY → KRW via live rates)
- International shipping estimate (small parcel)
- Korean customs duty + VAT (목록통관 vs 일반통관)
- Domestic shipping (when seller pays)
- Platform commissions
"""
from __future__ import annotations

from dataclasses import dataclass, field
from rich.console import Console
from rich.table import Table
from rich import box
from .exchange import to_krw, current_rates

console = Console()

# 판매 플랫폼별 수수료 (2026 기준 추정치, 결제 수수료 포함 대략치)
PLATFORM_FEES: dict[str, float] = {
    "smartstore": 0.0374,   # 네이버 스마트스토어 (등급 최소 기준 + 네이버페이)
    "coupang":    0.107,    # 쿠팡 (카테고리 평균)
    "11st":       0.08,     # 11번가
    "gmarket":    0.09,     # G마켓 / 옥션
    "self":       0.03,     # 자체몰 (PG 수수료만)
}

# 한국 직구 관세 기준 (개인 간이통관)
# - 미국발: USD 200 이하 면세
# - 그 외 국가(중국 등): USD 150 이하 면세
# 초과 시: 관세(품목별, 평균 8%) + 부가세 10%
CUSTOMS_THRESHOLD = {"USD_US": 200.0, "USD_OTHER": 150.0}
AVG_DUTY_RATE = 0.08
VAT_RATE = 0.10


@dataclass
class CostBreakdown:
    sourcing_krw: int
    intl_shipping_krw: int
    duty_krw: int
    vat_krw: int
    domestic_shipping_krw: int

    @property
    def total(self) -> int:
        return (
            self.sourcing_krw
            + self.intl_shipping_krw
            + self.duty_krw
            + self.vat_krw
            + self.domestic_shipping_krw
        )


@dataclass
class MarginResult:
    selling_price: int
    cost: CostBreakdown
    platform_fee_krw: int
    net_profit: int
    margin_rate: float  # net_profit / selling_price


def _customs(sourcing_usd: float, origin: str) -> tuple[int, int]:
    """Return (duty_krw, vat_krw). Applies only when threshold exceeded."""
    threshold_usd = (
        CUSTOMS_THRESHOLD["USD_US"] if origin == "US" else CUSTOMS_THRESHOLD["USD_OTHER"]
    )
    if sourcing_usd <= threshold_usd:
        return 0, 0
    sourcing_krw = to_krw(sourcing_usd, "USD")
    duty = round(sourcing_krw * AVG_DUTY_RATE)
    vat = round((sourcing_krw + duty) * VAT_RATE)
    return duty, vat


def calculate_cost(
    sourcing_amount: float,
    sourcing_currency: str = "USD",
    intl_shipping_krw: int = 3000,
    domestic_shipping_krw: int = 3000,
    origin: str = "CN",  # "US", "CN", "KR" 등
) -> CostBreakdown:
    """Compute per-unit landed cost in KRW."""
    sourcing_krw = to_krw(sourcing_amount, sourcing_currency)

    # 관세/부가세는 USD 환산액 기준으로 판정
    if sourcing_currency.upper() == "KRW":
        duty_krw, vat_krw = 0, 0
    else:
        sourcing_usd = (
            sourcing_amount
            if sourcing_currency.upper() == "USD"
            else to_krw(sourcing_amount, sourcing_currency) / current_rates()["USD_KRW"]
        )
        duty_krw, vat_krw = _customs(sourcing_usd, origin)

    return CostBreakdown(
        sourcing_krw=sourcing_krw,
        intl_shipping_krw=intl_shipping_krw,
        duty_krw=duty_krw,
        vat_krw=vat_krw,
        domestic_shipping_krw=domestic_shipping_krw,
    )


def analyze(
    sourcing_amount: float,
    sourcing_currency: str,
    selling_price: int,
    platform: str = "smartstore",
    intl_shipping_krw: int = 3000,
    domestic_shipping_krw: int = 3000,
    origin: str = "CN",
) -> MarginResult:
    cost = calculate_cost(
        sourcing_amount,
        sourcing_currency,
        intl_shipping_krw,
        domestic_shipping_krw,
        origin,
    )
    fee_rate = PLATFORM_FEES.get(platform, PLATFORM_FEES["smartstore"])
    platform_fee = round(selling_price * fee_rate)
    net = selling_price - cost.total - platform_fee
    margin_rate = net / selling_price if selling_price else 0.0
    return MarginResult(
        selling_price=selling_price,
        cost=cost,
        platform_fee_krw=platform_fee,
        net_profit=net,
        margin_rate=margin_rate,
    )


def break_even_price(
    sourcing_amount: float,
    sourcing_currency: str,
    platform: str = "smartstore",
    intl_shipping_krw: int = 3000,
    domestic_shipping_krw: int = 3000,
    origin: str = "CN",
) -> int:
    """Minimum selling price to cover all costs (margin = 0)."""
    cost = calculate_cost(
        sourcing_amount, sourcing_currency,
        intl_shipping_krw, domestic_shipping_krw, origin,
    ).total
    fee_rate = PLATFORM_FEES.get(platform, PLATFORM_FEES["smartstore"])
    # price * (1 - fee_rate) = cost  →  price = cost / (1 - fee_rate)
    return round(cost / (1 - fee_rate))


def recommended_prices(
    sourcing_amount: float,
    sourcing_currency: str,
    platform: str = "smartstore",
    target_margins: tuple[float, ...] = (0.2, 0.3, 0.5),
    intl_shipping_krw: int = 3000,
    domestic_shipping_krw: int = 3000,
    origin: str = "CN",
) -> dict[float, int]:
    """Return {margin_rate: recommended_selling_price}."""
    cost = calculate_cost(
        sourcing_amount, sourcing_currency,
        intl_shipping_krw, domestic_shipping_krw, origin,
    ).total
    fee_rate = PLATFORM_FEES.get(platform, PLATFORM_FEES["smartstore"])
    out = {}
    for m in target_margins:
        # price * (1 - fee_rate - m) = cost
        denom = 1 - fee_rate - m
        if denom <= 0:
            continue
        out[m] = round(cost / denom)
    return out


# ── Rich display helpers ─────────────────────────────────────────────────────

def render_breakdown(cost: CostBreakdown) -> Table:
    t = Table(title="원가 상세", box=box.ROUNDED)
    t.add_column("항목", style="cyan")
    t.add_column("금액", style="green", justify="right")
    t.add_row("소싱가", f"{cost.sourcing_krw:,}원")
    t.add_row("해외 배송비", f"{cost.intl_shipping_krw:,}원")
    if cost.duty_krw:
        t.add_row("관세", f"{cost.duty_krw:,}원")
        t.add_row("부가세", f"{cost.vat_krw:,}원")
    t.add_row("국내 배송비", f"{cost.domestic_shipping_krw:,}원")
    t.add_section()
    t.add_row("[bold]총 원가[/bold]", f"[bold]{cost.total:,}원[/bold]")
    return t


def render_margin(result: MarginResult, platform: str) -> Table:
    t = Table(title=f"마진 분석 ({platform})", box=box.ROUNDED)
    t.add_column("항목", style="cyan")
    t.add_column("금액", style="green", justify="right")
    t.add_row("판매가", f"{result.selling_price:,}원")
    t.add_row("총 원가", f"{result.cost.total:,}원")
    t.add_row("플랫폼 수수료", f"{result.platform_fee_krw:,}원")
    t.add_section()
    color = "bold green" if result.net_profit > 0 else "bold red"
    t.add_row(f"[{color}]순수익[/{color}]", f"[{color}]{result.net_profit:,}원[/{color}]")
    t.add_row(f"[{color}]마진율[/{color}]", f"[{color}]{result.margin_rate*100:.1f}%[/{color}]")
    return t


def render_recommendations(recs: dict[float, int]) -> Table:
    t = Table(title="권장 판매가", box=box.ROUNDED)
    t.add_column("목표 마진", style="cyan", justify="center")
    t.add_column("판매가", style="green", justify="right")
    for margin, price in sorted(recs.items()):
        t.add_row(f"{int(margin*100)}%", f"{price:,}원")
    return t
