"""
Asynchronous website lead enricher for extracting direct emails, social media handles, and contact pages.
"""
import asyncio
import re
from typing import List, Optional, Set
from urllib.parse import urljoin, urlparse
import aiohttp
from bs4 import BeautifulSoup

from src.config import (
    DEFAULT_USER_AGENTS,
    DEFAULT_ENRICH_CONCURRENCY,
    DEFAULT_ENRICH_TIMEOUT_SEC,
    CONTACT_SUBPAGES,
)
from src.models import BusinessLead
from src.utils import clean_url, extract_valid_emails, extract_social_links, to_proxy_url


class WebsiteEnricher:
    """High-concurrency async crawler that enriches business leads with emails and social profiles."""

    def __init__(
        self,
        concurrency: int = DEFAULT_ENRICH_CONCURRENCY,
        timeout_sec: int = DEFAULT_ENRICH_TIMEOUT_SEC,
        max_subpages: int = 2,
        proxy: Optional[str] = None,
    ):
        self.concurrency = concurrency
        self.timeout_sec = timeout_sec
        self.max_subpages = max_subpages
        self.proxy = to_proxy_url(proxy)
        self.semaphore = asyncio.Semaphore(concurrency)

    async def _fetch_html(self, session: aiohttp.ClientSession, url: str) -> Optional[str]:
        """Fetch raw HTML for a given URL with error handling."""
        try:
            headers = {
                "User-Agent": DEFAULT_USER_AGENTS[0],
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
            async with session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.timeout_sec),
                ssl=False,
                allow_redirects=True,
                proxy=self.proxy,
            ) as response:
                if response.status == 200:
                    content_type = response.headers.get("Content-Type", "")
                    if "text/html" in content_type or "text/plain" in content_type:
                        return await response.text(errors="ignore")
        except Exception:
            pass
        return None

    def _discover_contact_links(self, html: str, base_url: str) -> List[str]:
        """Discover contact, about, and team page URLs from HTML links."""
        discovered: List[str] = []
        seen: Set[str] = set()

        try:
            soup = BeautifulSoup(html, "html.parser")
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"].strip()
                if not href or href.startswith("#") or href.startswith("javascript:"):
                    continue

                full_url = urljoin(base_url, href)
                parsed_full = urlparse(full_url)
                parsed_base = urlparse(base_url)

                # Ensure same domain
                if parsed_full.netloc.lower() != parsed_base.netloc.lower():
                    continue

                path_lower = parsed_full.path.lower()
                for sub in CONTACT_SUBPAGES:
                    if sub in path_lower:
                        clean_link = f"{parsed_full.scheme}://{parsed_full.netloc}{parsed_full.path}"
                        if clean_link not in seen and clean_link != base_url:
                            seen.add(clean_link)
                            discovered.append(clean_link)
                            break
        except Exception:
            pass

        return discovered[: self.max_subpages]

    async def enrich_lead(self, session: aiohttp.ClientSession, lead: BusinessLead) -> BusinessLead:
        """Enrich a single BusinessLead with contact information from its website."""
        if not lead.website:
            lead.enrichment_status = "no_website"
            return lead

        website_url = clean_url(lead.website)
        if not website_url:
            lead.enrichment_status = "invalid_website"
            return lead

        async with self.semaphore:
            all_emails: Set[str] = set()
            socials_collected = {
                "linkedin": None,
                "facebook": None,
                "instagram": None,
                "twitter": None,
                "youtube": None,
                "tiktok": None,
                "pinterest": None,
            }
            contact_page: Optional[str] = None

            try:
                # 1. Fetch Homepage
                home_html = await self._fetch_html(session, website_url)
                if home_html:
                    # Extract emails
                    for email in extract_valid_emails(home_html):
                        all_emails.add(email)

                    # Extract socials
                    home_socials = extract_social_links(home_html, base_url=website_url)
                    for k, v in home_socials.items():
                        if v and not socials_collected[k]:
                            socials_collected[k] = v

                    # 2. Discover and visit contact / about subpages
                    contact_links = self._discover_contact_links(home_html, website_url)
                    if contact_links:
                        contact_page = contact_links[0]
                        for sub_url in contact_links:
                            sub_html = await self._fetch_html(session, sub_url)
                            if sub_html:
                                for email in extract_valid_emails(sub_html):
                                    all_emails.add(email)
                                sub_socials = extract_social_links(sub_html, base_url=website_url)
                                for k, v in sub_socials.items():
                                    if v and not socials_collected[k]:
                                        socials_collected[k] = v

                    lead.emails = sorted(list(all_emails))
                    lead.primary_email = self._select_primary_email(lead.emails)
                    lead.linkedin = socials_collected["linkedin"]
                    lead.facebook = socials_collected["facebook"]
                    lead.instagram = socials_collected["instagram"]
                    lead.twitter = socials_collected["twitter"]
                    lead.youtube = socials_collected["youtube"]
                    lead.tiktok = socials_collected["tiktok"]
                    lead.contact_page_url = contact_page
                    lead.enrichment_status = "enriched"
                else:
                    lead.enrichment_status = "unreachable"
            except Exception as e:
                lead.enrichment_status = f"error: {str(e)[:30]}"

            return lead

    def _select_primary_email(self, emails: List[str]) -> Optional[str]:
        """Heuristic to select the most relevant primary email."""
        if not emails:
            return None
        # Prefer common business inboxes if available
        priority_prefixes = ["info@", "contact@", "hello@", "support@", "sales@", "team@", "admin@"]
        for prefix in priority_prefixes:
            for email in emails:
                if email.lower().startswith(prefix):
                    return email
        return emails[0]

    async def enrich_leads_batch(
        self,
        leads: List[BusinessLead],
        progress_callback: Optional[callable] = None,
    ) -> List[BusinessLead]:
        """Enrich a batch of business leads concurrently."""
        connector = aiohttp.TCPConnector(limit=self.concurrency * 2, ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            tasks = []
            for lead in leads:
                tasks.append(self._enrich_with_callback(session, lead, progress_callback))
            enriched = await asyncio.gather(*tasks)
        return list(enriched)

    async def _enrich_with_callback(
        self,
        session: aiohttp.ClientSession,
        lead: BusinessLead,
        callback: Optional[callable] = None,
    ) -> BusinessLead:
        res = await self.enrich_lead(session, lead)
        if callback:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(res)
                else:
                    callback(res)
            except Exception:
                pass
        return res
