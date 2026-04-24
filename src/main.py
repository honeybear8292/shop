import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt, IntPrompt, FloatPrompt

from .config import ANTHROPIC_API_KEY, NAVER_CLIENT_ID, SUPPORTED_CATEGORIES
from .researcher import research_trending_products
from .price_finder import (
    find_all_prices,
    build_naver_table,
    build_stats_table,
    build_competition_table,
)
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
from .scorer import calculate_score, render_score
from .exchange import current_rates
from .storage import save_research, save_prices, save_expansion
from .batch import run_batch
from . import cache as cache_mod

console = Console()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _print_welcome():
    rates = current_rates()
    stats = cache_mod.stats()
    cache_summary = (
        " · ".join(f"{ns} {n}" for ns, n in stats.items()) if stats else "비어있음"
    )
    console.print(Panel.fit(
        "[bold cyan]쇼핑몰 상품 탐색기[/bold cyan]\n"
        "[dim]트렌드 · 최저가 · 마진 · 키워드확장 · 일괄처리[/dim]\n"
        f"[dim]환율: 1 USD = {rates['USD_KRW']:,.0f}원 · "
        f"1 CNY = {rates['CNY_KRW']:,.0f}원[/dim]\n"
        f"[dim]캐시: {cache_summary}[/dim]",
        border_style="cyan",
        padding=(1, 4),
    ))


_COMMANDS_NEED_ANTHROPIC = {"research", "price", "full", "expand", None}
_COMMANDS_NEED_NAVER = {"price", "full", "expand", "batch", None}


def _check_config(command: str | None):
    if command in _COMMANDS_NEED_ANTHROPIC and not ANTHROPIC_API_KEY:
        console.print("[bold red]오류: ANTHROPIC_API_KEY가 설정되지 않았습니다.[/bold red]")
        console.print("  .env 파일에 키를 입력하거나 환경변수를 설정해주세요.")
        sys.exit(1)
    if command in _COMMANDS_NEED_NAVER and not NAVER_CLIENT_ID:
        console.print(
            "[yellow]⚠ 네이버 API 키 없음 → 국내 가격/경쟁 분석은 건너뜁니다.[/yellow]"
        )


def _save_and_notify(fn, *args, **kwargs):
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
        if data.get("competition"):
            console.print(build_competition_table(data["competition"]))
            # Compute and display suitability score (margin unknown without sourcing cost)
            score = calculate_score(
                margin_rate=None,
                competition=data["competition"],
                naver_stats=data["stats"],
            )
            console.print(render_score(score, product))
            data["score"] = {
                "total": score.total,
                "verdict": score.verdict,
                "margin": score.margin,
                "competition": score.competition,
                "stability": score.stability,
                "demand": score.demand,
            }
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


def cmd_batch(args):
    input_path = Path(args.input)
    if not input_path.exists():
        console.print(f"[red]파일 없음: {input_path}[/red]")
        sys.exit(1)
    output_path = Path(args.output) if args.output else None
    run_batch(
        input_path,
        output_path=output_path,
        platform=args.platform,
        intl_shipping=args.intl_ship,
        domestic_shipping=args.dom_ship,
        origin=args.origin,
        default_target_margin=args.target_margin,
    )


def cmd_cache(args):
    if args.action == "stats":
        s = cache_mod.stats()
        if not s:
            console.print("[dim]캐시 비어있음[/dim]")
            return
        for ns, n in s.items():
            console.print(f"  [cyan]{ns}[/cyan]: {n}개")
    elif args.action == "clear":
        n = cache_mod.clear(args.namespace)
        ns_label = args.namespace or "전체"
        console.print(f"[green]✓ {ns_label} 캐시 삭제 완료 ({n}개)[/green]")


def cmd_interactive(_args=None):
    """Menu-driven interactive mode (no sub-command given)."""
    category_list = "\n".join(
        f"  [cyan]{i+1}.[/cyan] {c}" for i, c in enumerate(SUPPORTED_CATEGORIES)
    )
    console.print(Panel(category_list, title="지원 카테고리 (예시)", border_style="dim"))

    while True:
        console.print("\n[bold]메뉴[/bold]")
        console.print("  [cyan]1.[/cyan] 카테고리 트렌드 분석")
        console.print("  [cyan]2.[/cyan] 상품 최저가 검색 (점수 포함)")
        console.print("  [cyan]3.[/cyan] 통합 분석 (트렌드 + 가격)")
        console.print("  [cyan]4.[/cyan] 카테고리 키워드 확장 (한 번에 여러 상품)")
        console.print("  [cyan]5.[/cyan] 마진 계산기")
        console.print("  [cyan]6.[/cyan] CSV 일괄 처리")
        console.print("  [cyan]7.[/cyan] 캐시 관리")
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
        elif choice == "6":
            _interactive_batch()
        elif choice == "7":
            _interactive_cache()
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


def _interactive_batch():
    console.print("\n[bold]CSV 일괄 처리[/bold]")
    console.print("[dim]CSV 형식: 'keyword' 컬럼 필수, 'sourcing_price' / 'currency' / 'target_margin' 선택[/dim]")
    path_str = Prompt.ask("입력 CSV 경로").strip()
    path = Path(path_str)
    if not path.exists():
        console.print(f"[red]파일 없음: {path}[/red]")
        return
    platform = Prompt.ask(
        "판매 플랫폼", choices=list(PLATFORM_FEES.keys()), default="smartstore"
    )
    target = float(Prompt.ask("목표 마진율 (예: 0.3 = 30%)", default="0.3"))
    run_batch(path, platform=platform, default_target_margin=target)


def _interactive_cache():
    console.print("\n[bold]캐시 관리[/bold]")
    s = cache_mod.stats()
    if s:
        for ns, n in s.items():
            console.print(f"  [cyan]{ns}[/cyan]: {n}개")
    else:
        console.print("[dim]캐시 비어있음[/dim]")
        return
    if Prompt.ask("\n전체 삭제?", choices=["y", "n"], default="n") == "y":
        n = cache_mod.clear()
        console.print(f"[green]✓ 삭제 완료 ({n}개)[/green]")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="shop",
        description="소규모 쇼핑몰 상품 탐색 · 가격 · 마진 도구",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "예시:\n"
            "  python run.py                                       # 대화형 메뉴\n"
            "  python run.py research 문구류\n"
            "  python run.py price '고양이 자동 급수기'\n"
            "  python run.py full 애완용품\n"
            "  python run.py expand 문구류 --count 10\n"
            "  python run.py margin --source 5.99 --sell 25000\n"
            "  python run.py batch products.csv\n"
            "  python run.py cache stats\n"
            "  python run.py cache clear --namespace overseas\n"
        ),
    )
    subparsers = parser.add_subparsers(dest="command")

    p = subparsers.add_parser("research", help="카테고리 트렌드 분석")
    p.add_argument("category")
    p.set_defaults(func=cmd_research)

    p = subparsers.add_parser("price", help="상품 최저가 + 점수 분석")
    p.add_argument("product")
    p.set_defaults(func=cmd_price)

    p = subparsers.add_parser("full", help="트렌드 분석 후 선택 상품 가격 검색")
    p.add_argument("category")
    p.set_defaults(func=cmd_full)

    p = subparsers.add_parser(
        "expand", help="카테고리를 키워드로 확장 후 점수 순 정렬"
    )
    p.add_argument("category")
    p.add_argument("--count", type=int, default=10)
    p.set_defaults(func=cmd_expand)

    p = subparsers.add_parser("margin", help="마진 계산기")
    p.add_argument("--source", type=float, required=True)
    p.add_argument("--currency", default="USD", choices=["USD", "CNY", "KRW"])
    p.add_argument("--sell", type=int, default=None)
    p.add_argument("--platform", default="smartstore", choices=list(PLATFORM_FEES.keys()))
    p.add_argument("--intl-ship", type=int, default=3000)
    p.add_argument("--dom-ship", type=int, default=3000)
    p.add_argument("--origin", default="CN", choices=["CN", "US", "KR", "JP", "기타"])
    p.set_defaults(func=cmd_margin)

    p = subparsers.add_parser("batch", help="CSV 일괄 가격·점수 분석")
    p.add_argument("input", help="입력 CSV 경로")
    p.add_argument("--output", help="출력 CSV 경로 (기본: <input>_enriched.csv)")
    p.add_argument("--platform", default="smartstore", choices=list(PLATFORM_FEES.keys()))
    p.add_argument("--intl-ship", type=int, default=3000)
    p.add_argument("--dom-ship", type=int, default=3000)
    p.add_argument("--origin", default="CN", choices=["CN", "US", "KR", "JP", "기타"])
    p.add_argument("--target-margin", type=float, default=0.3, help="기본 목표 마진 (기본 0.3)")
    p.set_defaults(func=cmd_batch)

    p = subparsers.add_parser("cache", help="캐시 관리")
    p.add_argument("action", choices=["stats", "clear"])
    p.add_argument("--namespace", default=None, help="특정 네임스페이스만")
    p.set_defaults(func=cmd_cache)

    args = parser.parse_args()

    _print_welcome()
    _check_config(args.command)

    if args.command is None:
        cmd_interactive()
    else:
        args.func(args)
