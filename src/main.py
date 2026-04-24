import argparse
import sys

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

from .config import ANTHROPIC_API_KEY, NAVER_CLIENT_ID, SUPPORTED_CATEGORIES
from .researcher import research_trending_products
from .price_finder import find_all_prices, build_naver_table

console = Console()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _print_welcome():
    console.print(Panel.fit(
        "[bold cyan]쇼핑몰 상품 탐색기[/bold cyan]\n"
        "[dim]트렌드 분석 + 최저가 구매처 검색 (국내 · AliExpress · 1688)[/dim]",
        border_style="cyan",
        padding=(1, 4),
    ))


def _check_config():
    if not ANTHROPIC_API_KEY:
        console.print("[bold red]오류: ANTHROPIC_API_KEY가 설정되지 않았습니다.[/bold red]")
        console.print("  .env 파일에 키를 입력하거나 환경변수를 설정해주세요.")
        sys.exit(1)
    if not NAVER_CLIENT_ID:
        console.print(
            "[yellow]⚠ 네이버 API 키 없음 → 국내 최저가 검색은 건너뜁니다.[/yellow]"
        )


def _show_research(category: str):
    text = research_trending_products(category)
    console.print(Panel(
        Markdown(text),
        title=f"[bold green]{category} 트렌드 분석[/bold green]",
        border_style="green",
    ))


def _show_prices(product: str):
    data = find_all_prices(product)

    if data["naver"]:
        console.print(build_naver_table(data["naver"], product))
    else:
        console.print("[dim]네이버 결과 없음[/dim]")

    if data["overseas"]:
        console.print(Panel(
            Markdown(data["overseas"]),
            title="[bold blue]해외 구매처 (AliExpress · 1688 · Alibaba)[/bold blue]",
            border_style="blue",
        ))


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


def cmd_interactive(_args=None):
    """Menu-driven interactive mode (no sub-command given)."""
    category_list = "\n".join(
        f"  [cyan]{i+1}.[/cyan] {c}" for i, c in enumerate(SUPPORTED_CATEGORIES)
    )
    console.print(Panel(category_list, title="지원 카테고리", border_style="dim"))

    while True:
        console.print("\n[bold]메뉴[/bold]")
        console.print("  [cyan]1.[/cyan] 카테고리 트렌드 분석")
        console.print("  [cyan]2.[/cyan] 상품 최저가 검색")
        console.print("  [cyan]3.[/cyan] 통합 분석 (트렌드 + 가격)")
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
                prod = Prompt.ask(
                    "가격 조회할 상품명 (건너뛰려면 Enter)"
                ).strip()
                if prod:
                    _show_prices(prod)
        else:
            console.print("[red]잘못된 입력입니다.[/red]")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    _print_welcome()
    _check_config()

    parser = argparse.ArgumentParser(
        prog="shop",
        description="소규모 쇼핑몰 상품 탐색 + 최저가 검색 도구",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "예시:\n"
            "  python run.py                        # 대화형 메뉴\n"
            "  python run.py research 문구류\n"
            "  python run.py price '고양이 자동 급수기'\n"
            "  python run.py full 애완용품\n"
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

    args = parser.parse_args()

    if args.command is None:
        cmd_interactive()
    else:
        args.func(args)
