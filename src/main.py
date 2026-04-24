import argparse
import sys

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt, IntPrompt, FloatPrompt

from .config import ANTHROPIC_API_KEY, NAVER_CLIENT_ID, SUPPORTED_CATEGORIES
from .researcher import research_trending_products
from .price_finder import find_all_prices, build_naver_table, build_stats_table
from .expander import expand_with_prices, render_expansion
from .margin import (
    PLATFORM_FEES,
    analyze,
    break_even_price,
    recommended_prices,
    render_breakdown,
    render_margin,
    render_recommendations,
)
from .exchange import current_rates
from .storage import save_research, save_prices, save_expansion

console = Console()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _print_welcome():
    rates = current_rates()
    console.print(Panel.fit(
        "[bold cyan]쇼핑몰 상품 탐색기[/bold cyan]\n"
        "[dim]트렌드 분석 · 최저가 검색 · 마진 계산 · 키워드 확장[/dim]\n"
        f"[dim]환율: 1 USD = {rates['USD_KRW']:,.0f}원 · "
        f"1 CNY = {rates['CNY_KRW']:,.0f}원[/dim]",
        border_style="cyan",
        padding=(1, 4),
    ))


_COMMANDS_NEED_ANTHROPIC = {"research", "price", "full", "expand", None}


def _check_config(command: str | None):
    if command in _COMMANDS_NEED_ANTHROPIC and not ANTHROPIC_API_KEY:
        console.print("[bold red]오류: ANTHROPIC_API_KEY가 설정되지 않았습니다.[/bold red]")
        console.print("  .env 파일에 키를 입력하거나 환경변수를 설정해주세요.")
        sys.exit(1)
    if command in {"price", "full", "expand", None} and not NAVER_CLIENT_ID:
        console.print(
            "[yellow]⚠ 네이버 API 키 없음 → 국내 최저가 검색은 건너뜁니다.[/yellow]"
        )


def _save_and_notify(fn, *args, **kwargs):
    """Save result; display the resulting path(s)."""
    try:
        out = fn(*args, **kwargs)
    except Exception as exc:
        console.print(f"[red]저장 실패: {exc}[/red]")
        return
    if isinstance(out, tuple):
        for p in out:
            console.print(f"[dim]💾 저장: {p}[/dim]")
    else:
        console.print(f"[dim]💾 저장: {out}[/dim]")


def _show_research(category: str, save: bool = True):
    text = research_trending_products(category)
    console.print(Panel(
        Markdown(text),
        title=f"[bold green]{category} 트렌드 분석[/bold green]",
        border_style="green",
    ))
    if save:
        _save_and_notify(save_research, category, text)


def _show_prices(product: str, save: bool = True):
    data = find_all_prices(product)

    if data["naver"]:
        console.print(build_naver_table(data["naver"], product))
        if data.get("stats"):
            console.print(build_stats_table(data["stats"]))
    else:
        console.print("[dim]네이버 결과 없음[/dim]")

    if data["overseas"]:
        console.print(Panel(
            Markdown(data["overseas"]),
            title="[bold blue]해외 구매처 (AliExpress · 1688 · Alibaba)[/bold blue]",
            border_style="blue",
        ))

    if save:
        _save_and_notify(save_prices, product, data)


def _show_expansion(category: str, count: int = 10, save: bool = True):
    rows = expand_with_prices(category, count)
    if not rows:
        return
    console.print(render_expansion(category, rows))
    if save:
        _save_and_notify(save_expansion, category, rows)


def _show_margin(
    sourcing_amount: float,
    currency: str,
    selling_price: int | None,
    platform: str,
    intl_shipping: int,
    domestic_shipping: int,
    origin: str,
):
    cost = analyze(
        sourcing_amount, currency,
        selling_price or 0, platform,
        intl_shipping, domestic_shipping, origin,
    ).cost
    console.print(render_breakdown(cost))

    recs = recommended_prices(
        sourcing_amount, currency, platform,
        intl_shipping_krw=intl_shipping,
        domestic_shipping_krw=domestic_shipping,
        origin=origin,
    )
    bep = break_even_price(
        sourcing_amount, currency, platform,
        intl_shipping_krw=intl_shipping,
        domestic_shipping_krw=domestic_shipping,
        origin=origin,
    )
    console.print(f"\n[bold]손익분기 판매가:[/bold] {bep:,}원")
    console.print(render_recommendations(recs))

    if selling_price:
        result = analyze(
            sourcing_amount, currency, selling_price, platform,
            intl_shipping, domestic_shipping, origin,
        )
        console.print(render_margin(result, platform))


# ── Sub-commands ─────────────────────────────────────────────────────────────

def cmd_research(args):
    _show_research(args.category)


def cmd_price(args):
    _show_prices(args.product)


def cmd_full(args):
    _show_research(args.category)
    console.rule()
    product = Prompt.ask(
        "\n[bold]어떤 상품의 가격을 조회할까요?[/bold] (건너뛰려면 Enter)"
    ).strip()
    if product:
        _show_prices(product)


def cmd_expand(args):
    _show_expansion(args.category, args.count)


def cmd_margin(args):
    _show_margin(
        sourcing_amount=args.source,
        currency=args.currency,
        selling_price=args.sell,
        platform=args.platform,
        intl_shipping=args.intl_ship,
        domestic_shipping=args.dom_ship,
        origin=args.origin,
    )


def cmd_interactive(_args=None):
    """Menu-driven interactive mode (no sub-command given)."""
    category_list = "\n".join(
        f"  [cyan]{i+1}.[/cyan] {c}" for i, c in enumerate(SUPPORTED_CATEGORIES)
    )
    console.print(Panel(category_list, title="지원 카테고리 (예시)", border_style="dim"))

    while True:
        console.print("\n[bold]메뉴[/bold]")
        console.print("  [cyan]1.[/cyan] 카테고리 트렌드 분석")
        console.print("  [cyan]2.[/cyan] 상품 최저가 검색")
        console.print("  [cyan]3.[/cyan] 통합 분석 (트렌드 + 가격)")
        console.print("  [cyan]4.[/cyan] 카테고리 키워드 확장 (한 번에 여러 상품 가격)")
        console.print("  [cyan]5.[/cyan] 마진 계산기")
        console.print("  [cyan]0.[/cyan] 종료")

        choice = Prompt.ask("\n선택").strip()

        if choice == "0":
            console.print("[dim]종료합니다.[/dim]")
            break
        elif choice == "1":
            cat = Prompt.ask("카테고리 입력 (예: 문구류)").strip()
            if cat:
                _show_research(cat)
        elif choice == "2":
            prod = Prompt.ask("상품명 입력 (예: 고양이 자동 급수기)").strip()
            if prod:
                _show_prices(prod)
        elif choice == "3":
            cat = Prompt.ask("카테고리 입력").strip()
            if cat:
                _show_research(cat)
                console.rule()
                prod = Prompt.ask("가격 조회할 상품명 (Enter로 건너뜀)").strip()
                if prod:
                    _show_prices(prod)
        elif choice == "4":
            cat = Prompt.ask("카테고리 입력").strip()
            if cat:
                count = IntPrompt.ask("키워드 개수", default=10)
                _show_expansion(cat, count)
        elif choice == "5":
            _interactive_margin()
        else:
            console.print("[red]잘못된 입력입니다.[/red]")


def _interactive_margin():
    console.print("\n[bold]마진 계산기[/bold]")
    currency = Prompt.ask(
        "소싱 통화", choices=["USD", "CNY", "KRW"], default="USD"
    )
    source = FloatPrompt.ask(f"소싱 단가 ({currency})")
    platform = Prompt.ask(
        "판매 플랫폼",
        choices=list(PLATFORM_FEES.keys()),
        default="smartstore",
    )
    intl_ship = IntPrompt.ask("해외 배송비 (원/개)", default=3000)
    dom_ship = IntPrompt.ask("국내 배송비 (원/개)", default=3000)
    origin = Prompt.ask(
        "발송국 (관세 면세 기준: US=200 USD, 기타=150 USD)",
        choices=["CN", "US", "KR", "JP", "기타"],
        default="CN",
    )
    sell_input = Prompt.ask(
        "예상 판매가 (원, Enter로 생략하면 권장가만 표시)", default=""
    ).strip()
    sell = int(sell_input) if sell_input else None

    _show_margin(source, currency, sell, platform, intl_ship, dom_ship, origin)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="shop",
        description="소규모 쇼핑몰 상품 탐색 · 가격 · 마진 도구",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "예시:\n"
            "  python run.py                             # 대화형 메뉴\n"
            "  python run.py research 문구류\n"
            "  python run.py price '고양이 자동 급수기'\n"
            "  python run.py full 애완용품\n"
            "  python run.py expand 문구류 --count 10\n"
            "  python run.py margin --source 5.99 --sell 25000 --platform smartstore\n"
        ),
    )
    subparsers = parser.add_subparsers(dest="command")

    p = subparsers.add_parser("research", help="카테고리 트렌드 분석")
    p.add_argument("category", help="카테고리명 (예: 문구류)")
    p.set_defaults(func=cmd_research)

    p = subparsers.add_parser("price", help="상품 최저가 검색 (국내 + 해외)")
    p.add_argument("product", help="상품명 (예: 귀여운 스티커 세트)")
    p.set_defaults(func=cmd_price)

    p = subparsers.add_parser("full", help="트렌드 분석 후 선택 상품 가격 검색")
    p.add_argument("category", help="카테고리명")
    p.set_defaults(func=cmd_full)

    p = subparsers.add_parser(
        "expand", help="카테고리를 구체 키워드로 확장하고 각 가격대 조사"
    )
    p.add_argument("category", help="카테고리명")
    p.add_argument("--count", type=int, default=10, help="키워드 개수 (기본 10)")
    p.set_defaults(func=cmd_expand)

    p = subparsers.add_parser("margin", help="마진 계산기")
    p.add_argument("--source", type=float, required=True, help="소싱 단가")
    p.add_argument(
        "--currency", default="USD", choices=["USD", "CNY", "KRW"],
        help="소싱 통화 (기본 USD)",
    )
    p.add_argument("--sell", type=int, default=None, help="예상 판매가(원). 생략 시 권장가만 산출")
    p.add_argument(
        "--platform", default="smartstore",
        choices=list(PLATFORM_FEES.keys()),
        help="판매 플랫폼 (기본 smartstore)",
    )
    p.add_argument("--intl-ship", type=int, default=3000, help="해외 배송비(원/개)")
    p.add_argument("--dom-ship", type=int, default=3000, help="국내 배송비(원/개)")
    p.add_argument(
        "--origin", default="CN", choices=["CN", "US", "KR", "JP", "기타"],
        help="발송국 (관세 면세 기준)",
    )
    p.set_defaults(func=cmd_margin)

    args = parser.parse_args()

    _print_welcome()
    _check_config(args.command)

    if args.command is None:
        cmd_interactive()
    else:
        args.func(args)
