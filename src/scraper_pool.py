"""
ScraperPool: runs N concurrent Google Maps scraper workers in parallel,
each assigned a dedicated proxy from the rotation pool.
"""
import asyncio
import threading
from typing import List, Optional, Callable, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime

from src.models import BusinessLead
from src.maps_scraper import GoogleMapsScraper
from src.utils import ProxyManager, load_proxies_from_file, deduplicate_leads


@dataclass
class WorkerResult:
    """Holds the result for a single scraper worker job."""
    query: str
    worker_id: int
    proxy: Optional[str]
    leads: List[BusinessLead] = field(default_factory=list)
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    @property
    def duration_sec(self) -> float:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return 0.0


class ScraperPool:
    """
    Runs multiple GoogleMapsScraper instances concurrently.

    Each worker in the pool processes one query at a time and picks a
    dedicated proxy from the rotation list in round-robin order so that
    concurrent workers always use different IPs.

    Args:
        threads:                 Max concurrent scraper workers.
        headless:                Run browsers headlessly.
        delay:                   Per-action delay in seconds per worker.
        proxy:                   Single proxy string (used for all workers).
        proxy_file:              Text file of rotating proxies (one per line).
        proxies:                 Explicit list of proxy strings.
        enable_captcha_solver:   Load Bit Solver extension into each browser.
        solver_ext:              'captchasonic' | 'nopecha'.
        solver_path:             Custom extension directory path.
        lead_callback:           Called from any worker when a lead is extracted.
        worker_callback:         Called when a worker completes its query.
    """

    def __init__(
        self,
        threads: int = 3,
        headless: bool = True,
        delay: float = 1.0,
        proxy: Optional[str] = None,
        proxy_file: Optional[str] = None,
        proxies: Optional[List[str]] = None,
        enable_captcha_solver: bool = False,
        solver_ext: str = "captchasonic",
        solver_path: Optional[str] = None,
        lead_callback: Optional[Callable[[BusinessLead, int], None]] = None,
        worker_callback: Optional[Callable[[WorkerResult], None]] = None,
    ):
        self.threads = max(1, threads)
        self.headless = headless
        self.delay = delay
        self.enable_captcha_solver = enable_captcha_solver
        self.solver_ext = solver_ext
        self.solver_path = solver_path
        self.lead_callback = lead_callback
        self.worker_callback = worker_callback

        # Build unified proxy pool
        self.proxy_manager = ProxyManager()
        if proxies:
            self.proxy_manager.add_proxies(proxies)
        if proxy:
            self.proxy_manager.add_proxies([proxy])
        if proxy_file:
            self.proxy_manager.add_proxies(load_proxies_from_file(proxy_file))

        self._lock = asyncio.Lock()
        self._all_leads: List[BusinessLead] = []

    def _build_worker_scraper(self, proxy_str: Optional[str]) -> GoogleMapsScraper:
        """Build a dedicated GoogleMapsScraper for one worker thread."""
        return GoogleMapsScraper(
            headless=self.headless,
            delay=self.delay,
            proxy=proxy_str,
            enable_captcha_solver=self.enable_captcha_solver,
            solver_ext=self.solver_ext,
            solver_path=self.solver_path,
        )

    async def _run_worker(
        self,
        worker_id: int,
        query: str,
        limit: int,
        proxy_str: Optional[str],
        semaphore: asyncio.Semaphore,
    ) -> WorkerResult:
        """Execute one scraping job in a semaphore-limited worker."""
        result = WorkerResult(
            query=query,
            worker_id=worker_id,
            proxy=proxy_str,
            started_at=datetime.now(),
        )

        async with semaphore:
            try:
                scraper = self._build_worker_scraper(proxy_str)

                async def on_lead(lead: BusinessLead):
                    lead.search_query = query
                    result.leads.append(lead)
                    async with self._lock:
                        self._all_leads.append(lead)
                    if self.lead_callback:
                        try:
                            if asyncio.iscoroutinefunction(self.lead_callback):
                                await self.lead_callback(lead, worker_id)
                            else:
                                self.lead_callback(lead, worker_id)
                        except Exception:
                            pass

                try:
                    leads = await asyncio.wait_for(
                        scraper.scrape_query(
                            query=query,
                            limit=limit,
                            lead_callback=on_lead,
                        ),
                        timeout=50.0,
                    )
                    # scrape_query returns deduped list — merge any missed ones
                    for lead in leads:
                        if lead not in result.leads:
                            result.leads.append(lead)
                except asyncio.TimeoutError:
                    if not result.leads:
                        result.error = "Worker watchdog: query timed out after 50s"

            except Exception as e:
                result.error = str(e)

        result.finished_at = datetime.now()

        if self.worker_callback:
            try:
                if asyncio.iscoroutinefunction(self.worker_callback):
                    await self.worker_callback(result)
                else:
                    self.worker_callback(result)
            except Exception:
                pass

        return result

    async def run(
        self,
        queries: List[str],
        limit_per_query: int = 20,
    ) -> List[WorkerResult]:
        """
        Run all queries across the pool concurrently.

        Queries are distributed across `self.threads` workers. Each worker
        picks the next available proxy in round-robin order so parallel
        workers always hit a different IP.

        Args:
            queries:           List of Google Maps search strings.
            limit_per_query:   Max leads to collect per query.

        Returns:
            List of WorkerResult objects, one per query.
        """
        self._all_leads.clear()
        semaphore = asyncio.Semaphore(self.threads)

        tasks = []
        for worker_id, query in enumerate(queries, start=1):
            proxy_str = self.proxy_manager.get_next_proxy_str() if len(self.proxy_manager) > 0 else None
            tasks.append(
                self._run_worker(
                    worker_id=worker_id,
                    query=query,
                    limit=limit_per_query,
                    proxy_str=proxy_str,
                    semaphore=semaphore,
                )
            )

        results: List[WorkerResult] = await asyncio.gather(*tasks)
        return list(results)

    def get_all_leads(self, deduplicate: bool = True) -> List[BusinessLead]:
        """Return all collected leads, optionally deduplicated."""
        if deduplicate:
            return deduplicate_leads(self._all_leads)
        return list(self._all_leads)
