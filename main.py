"""
Google Maps Lead Generation Scraper - CLI Interface
"""
import argparse
import asyncio
import sys
import os
from datetime import datetime
from typing import List, Optional

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.live import Live
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn, TaskID

from src.models import BusinessLead, ScrapeConfig
from src.maps_scraper import GoogleMapsScraper
from src.enricher import WebsiteEnricher
from src.exporter import export_leads
from src.scraper_pool import ScraperPool, WorkerResult
from src.utils import deduplicate_leads, load_proxies_from_file, filter_leads
from src.geo_expander import generate_sub_queries

console = Console()


def print_banner():
    """Display CLI Welcome Banner."""
    banner_text = """[bold cyan]Google Maps Lead Generation Scraper[/bold cyan]
[dim]Extract high-value B2B leads, emails, phones, and social profiles with ease.[/dim]"""
    console.print(Panel(banner_text, border_style="cyan", expand=False))


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Scrape Google Maps listings and enrich leads with emails & social media profiles.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    query_group = parser.add_mutually_exclusive_group(required=True)
    query_group.add_argument(
        "-q", "--query",
        type=str,
        help="Search query (e.g. 'Dentists in Austin, TX')",
    )
    query_group.add_argument(
        "-f", "--file",
        type=str,
        help="Path to a text file containing queries (one per line)",
    )

    parser.add_argument(
        "-l", "--limit",
        type=int,
        default=20,
        help="Max results to scrape per query (0 for unlimited)",
    )
    parser.add_argument(
        "--enrich",
        action="store_true",
        default=True,
        help="Enrich leads by crawling business websites for emails & social media",
    )
    parser.add_argument(
        "--no-enrich",
        dest="enrich",
        action="store_false",
        help="Skip website email & social media enrichment",
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="Output filepath (e.g. 'leads.csv' or 'leads.xlsx')",
    )
    parser.add_argument(
        "--format",
        choices=["csv", "xlsx", "json", "all"],
        default="csv",
        help="Output export format",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=True,
        help="Run browser in headless mode",
    )
    parser.add_argument(
        "--no-headless",
        dest="headless",
        action="store_false",
        help="Run browser in visible (headful) mode for debugging",
    )

    # Threading
    parser.add_argument(
        "-t", "--threads",
        type=int,
        default=1,
        help="Number of concurrent browser workers (each uses a separate proxy if available)",
    )

    # Enrichment
    parser.add_argument(
        "--concurrency",
        type=int,
        default=10,
        help="Max concurrent requests for website enrichment",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay between actions in seconds",
    )

    # Proxy
    parser.add_argument(
        "--proxy",
        type=str,
        default=None,
        help="Single HTTP/SOCKS proxy (e.g. 'http://user:pass@host:port')",
    )
    parser.add_argument(
        "--proxy-file",
        type=str,
        default=None,
        help="Path to a text file containing rotating proxies (one per line)",
    )
    parser.add_argument(
        "--proxies",
        type=str,
        nargs="+",
        default=None,
        help="Space-separated list of proxies (e.g. --proxies http://p1:8080 http://p2:8080)",
    )

    # Bit Solver (Captcha)
    parser.add_argument(
        "--captcha-solver",
        action="store_true",
        default=False,
        help="Enable Bit Solver browser extension to automatically solve CAPTCHAs",
    )
    parser.add_argument(
        "--solver-ext",
        choices=["captchasonic", "nopecha"],
        default="captchasonic",
        help="Bit Solver extension to use ('captchasonic' or 'nopecha')",
    )
    parser.add_argument(
        "--solver-path",
        type=str,
        default=None,
        help="Custom path to unpacked Captcha solver extension directory",
    )

    # Lead Filtering Options (Web Builder & Outreach Targeting)
    parser.add_argument(
        "--no-website-only",
        action="store_true",
        default=False,
        help="Only export leads without a website (ideal for website builders & web design agencies)",
    )
    parser.add_argument(
        "--has-website-only",
        action="store_true",
        default=False,
        help="Only export leads that DO have a website",
    )
    parser.add_argument(
        "--require-contact",
        action="store_true",
        default=True,
        help="Keep only leads with at least 1 contact info (phone/email) or 1 social profile (default: True)",
    )
    parser.add_argument(
        "--no-require-contact",
        dest="require_contact",
        action="store_false",
        help="Keep all leads, even if uncontactable (no phone, email, or social media)",
    )
    parser.add_argument(
        "--require-phone-email",
        action="store_true",
        default=False,
        help="Only export leads that have BOTH phone and email linked",
    )
    parser.add_argument(
        "--min-reviews",
        type=int,
        default=None,
        help="Only export leads with at least N Google Maps reviews (e.g. --min-reviews 10)",
    )
    parser.add_argument(
        "--max-reviews",
        type=int,
        default=None,
        help="Only export leads with at most N Google Maps reviews",
    )

    # Geo-Expansion Options (Scale past the 120 cap)
    parser.add_argument(
        "--expand-city",
        type=str,
        default=None,
        help="City/Metro area to auto-split into ZIP code sub-queries (e.g. 'Austin, TX' or 'Miami, FL')",
    )
    parser.add_argument(
        "--expand-subqueries",
        type=int,
        default=10,
        help="Number of ZIP code sub-queries to generate when using --expand-city (default: 10)",
    )
    parser.add_argument(
        "--country",
        type=str,
        default="us",
        help="Country code for postal lookup (default: 'us')",
    )

    return parser.parse_args()


def load_queries(args: argparse.Namespace) -> List[str]:
    """Load search queries from CLI, file, or auto-expand a city."""
    if args.expand_city and args.query:
        sub_qs = generate_sub_queries(
            niche=args.query,
            location=args.expand_city,
            country=args.country,
            limit=args.expand_subqueries,
        )
        console.print(f"[bold cyan]⚡ Geo-Expander generated {len(sub_qs)} ZIP sub-queries for '{args.query}' across '{args.expand_city}'[/bold cyan]")
        return sub_qs

    if args.query:
        return [args.query.strip()]
    if args.file:
        if not os.path.isfile(args.file):
            console.print(f"[bold red]Error:[/bold red] File not found: {args.file}")
            sys.exit(1)
        with open(args.file, "r", encoding="utf-8") as f:
            queries = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        if not queries:
            console.print(f"[bold red]Error:[/bold red] No valid queries found in {args.file}")
            sys.exit(1)
        return queries
    return []


def _count_proxies(args: argparse.Namespace) -> int:
    """Count total proxies available across all proxy sources."""
    total = 0
    if args.proxy:
        total += 1
    if args.proxy_file and os.path.isfile(args.proxy_file):
        total += len(load_proxies_from_file(args.proxy_file))
    if args.proxies:
        total += len(args.proxies)
    return total


async def run_scraper_pipeline(args: argparse.Namespace):
    """Execute the full scraping and enrichment pipeline."""
    queries = load_queries(args)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    proxy_count = _count_proxies(args)

    if not args.output:
        default_name = f"leads_{timestamp}.{args.format if args.format != 'all' else 'csv'}"
        output_path = os.path.join("outputs", default_name)
    else:
        output_path = args.output

    # Build display info
    effective_threads = min(args.threads, len(queries)) if len(queries) > 0 else args.threads
    console.print(f"\n[bold green]➜ Starting extraction for {len(queries)} query(s)...[/bold green]")
    console.print(f"  • Concurrent Threads:   [cyan]{effective_threads}[/cyan]")
    console.print(f"  • Limit per query:      [cyan]{args.limit or 'Unlimited'}[/cyan]")
    console.print(f"  • Website Enrichment:   [cyan]{'Enabled' if args.enrich else 'Disabled'}[/cyan]")
    console.print(f"  • Bit Solver (Captcha): [cyan]{'Enabled (' + args.solver_ext + ')' if args.captcha_solver else 'Disabled'}[/cyan]")
    console.print(f"  • Proxies Available:    [cyan]{proxy_count or 'None (direct)'}[/cyan]")
    console.print(f"  • Output Destination:   [cyan]{output_path}[/cyan]\n")

    # ── Phase 1: Concurrent Google Maps Scraping ──────────────────────────────
    all_leads: List[BusinessLead] = []
    worker_progress: dict = {}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[bold green]{task.completed}[/bold green] leads"),
        TimeElapsedColumn(),
        console=console,
        expand=True,
    ) as progress:
        # One Rich progress bar per query (row), keyed by query index
        task_ids: dict = {}
        for idx, q in enumerate(queries, 1):
            tid = progress.add_task(f"[yellow][W?][/yellow] {q[:50]}", total=args.limit or None)
            task_ids[q] = (idx, tid)

        def on_lead(lead: BusinessLead, worker_id: int):
            q = lead.search_query
            if q in task_ids:
                _, tid = task_ids[q]
                progress.update(
                    tid,
                    advance=1,
                    description=f"[yellow][W{worker_id}][/yellow] {q[:40]} — [green]{lead.name[:25]}[/green]",
                )
            all_leads.append(lead)

        def on_worker_done(result: WorkerResult):
            q = result.query
            if q in task_ids:
                _, tid = task_ids[q]
                status = f"[bold green]✓ {len(result.leads)} leads" if not result.error else f"[bold red]✗ {result.error[:30]}"
                proxy_tag = f" via {result.proxy[:28]}…" if result.proxy else ""
                progress.update(
                    tid,
                    description=f"[dim][W{result.worker_id}][/dim] {q[:35]}{proxy_tag} {status} ({result.duration_sec:.1f}s)",
                    completed=len(result.leads),
                )

        pool = ScraperPool(
            threads=args.threads,
            headless=args.headless,
            delay=args.delay,
            proxy=args.proxy,
            proxy_file=args.proxy_file,
            proxies=args.proxies,
            enable_captcha_solver=args.captcha_solver,
            solver_ext=args.solver_ext,
            solver_path=args.solver_path,
            lead_callback=on_lead,
            worker_callback=on_worker_done,
        )

        worker_results = await pool.run(queries=queries, limit_per_query=args.limit)

    # Deduplicate
    unique_leads = deduplicate_leads(pool.get_all_leads(deduplicate=False))
    console.print(f"\n[bold]Total unique leads extracted:[/bold] [bold green]{len(unique_leads)}[/bold green]")

    # Print per-worker summary
    worker_table = Table(title="Worker Summary", show_header=True, header_style="bold blue")
    worker_table.add_column("Worker", justify="center", style="cyan", width=8)
    worker_table.add_column("Query", style="dim")
    worker_table.add_column("Proxy", style="dim")
    worker_table.add_column("Leads", justify="right", style="green")
    worker_table.add_column("Duration", justify="right", style="yellow")
    worker_table.add_column("Status", justify="center")
    for r in worker_results:
        proxy_display = (r.proxy[:35] + "…") if r.proxy and len(r.proxy) > 35 else (r.proxy or "direct")
        status = "[green]✓ OK" if not r.error else f"[red]✗ ERR"
        worker_table.add_row(
            f"W{r.worker_id}", r.query[:45], proxy_display,
            str(len(r.leads)), f"{r.duration_sec:.1f}s", status
        )
    console.print(worker_table)

    # ── Phase 2: Website Enrichment ───────────────────────────────────────────
    if args.enrich and unique_leads:
        leads_with_websites = [l for l in unique_leads if l.website]
        console.print(f"\n[bold magenta]➜ Enriching {len(leads_with_websites)} leads from their websites...[/bold magenta]")

        enricher = WebsiteEnricher(concurrency=args.concurrency, proxy=args.proxy)
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Crawling websites for emails & socials...", total=len(leads_with_websites))

            def on_lead_enriched(lead: BusinessLead):
                email_info = f"({lead.primary_email})" if lead.primary_email else ""
                progress.update(task, advance=1, description=f"Enriched: [cyan]{lead.name[:25]}[/cyan] {email_info}")

            await enricher.enrich_leads_batch(unique_leads, progress_callback=on_lead_enriched)

    # ── Phase 3: Filtering & Export ───────────────────────────────────────────
    if unique_leads:
        total_raw = len(unique_leads)
        no_web_count = sum(1 for l in unique_leads if not l.has_website)
        has_web_count = sum(1 for l in unique_leads if l.has_website)
        with_phone = sum(1 for l in unique_leads if l.has_phone)
        with_email = sum(1 for l in unique_leads if l.has_email)
        with_both = sum(1 for l in unique_leads if l.has_phone_and_email)
        with_social = sum(1 for l in unique_leads if l.has_social)
        contactable_count = sum(1 for l in unique_leads if l.is_contactable)

        # Apply filtering based on user flags
        website_filter = "no_website" if args.no_website_only else ("has_website" if args.has_website_only else "all")
        final_leads = filter_leads(
            unique_leads,
            require_contact=args.require_contact,
            website_filter=website_filter,
            require_phone_and_email=args.require_phone_email,
            min_reviews=args.min_reviews,
            max_reviews=args.max_reviews,
        )

        total_reviews = sum(l.review_count or 0 for l in final_leads)
        avg_reviews = round(total_reviews / len(final_leads), 1) if final_leads else 0

        if final_leads:
            saved_file = export_leads(final_leads, output_path, export_format=args.format)
            console.print(f"\n[bold green]✓ Exported {len(final_leads)} leads to:[/bold green] [bold underline]{saved_file}[/bold underline]")
        else:
            console.print("\n[bold yellow]⚠️ No leads matched your specific filter criteria.[/bold yellow]")

        # Summary Table
        table = Table(title="Lead Generation & Outreach Summary", show_header=True, header_style="bold blue")
        table.add_column("Metric", style="dim")
        table.add_column("Count", justify="right", style="bold green")

        table.add_row("Total Raw Leads Scraped", str(total_raw))
        table.add_row("💬 Total Reviews Captured", f"{total_reviews:,}")
        table.add_row("⭐ Average Reviews / Business", str(avg_reviews))
        table.add_row("🎯 No Website (Web Design Targets)", f"{no_web_count} ({no_web_count/total_raw*100:.1f}%)" if total_raw else "0")
        table.add_row("🌐 With Website", f"{has_web_count} ({has_web_count/total_raw*100:.1f}%)" if total_raw else "0")
        table.add_row("📞 With Phone Number", f"{with_phone} ({with_phone/total_raw*100:.1f}%)" if total_raw else "0")
        table.add_row("✉️ With Direct Email", f"{with_email} ({with_email/total_raw*100:.1f}%)" if total_raw else "0")
        table.add_row("📞+✉️ With BOTH Phone & Email", f"{with_both} ({with_both/total_raw*100:.1f}%)" if total_raw else "0")
        table.add_row("📱 With Social Media (FB/IG/LinkedIn)", f"{with_social} ({with_social/total_raw*100:.1f}%)" if total_raw else "0")
        table.add_row("✅ Total Contactable Leads (Phone/Email/Social)", f"{contactable_count} ({contactable_count/total_raw*100:.1f}%)" if total_raw else "0")
        if len(final_leads) != total_raw:
            table.add_row("📥 Final Exported Leads (Filtered)", f"[bold cyan]{len(final_leads)}[/bold cyan]")
        console.print(table)
    else:
        console.print("[bold yellow]No leads were found for the given search criteria.[/bold yellow]")



def main():
    print_banner()
    args = parse_arguments()
    asyncio.run(run_scraper_pipeline(args))


if __name__ == "__main__":
    main()
