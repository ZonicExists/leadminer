"""
Google Maps Playwright Scraper with Proxy Rotation and Bit Solver (CAPTCHA) integration.
"""
import asyncio
import json
import os
import random
import re
import shutil
import tempfile
from typing import List, Optional, Callable, Dict, Any, Union
from urllib.parse import quote_plus
from playwright.async_api import async_playwright, Page, Browser, BrowserContext

from src.config import (
    DEFAULT_USER_AGENTS,
    DEFAULT_TIMEOUT_MS,
    DEFAULT_SCROLL_PAUSE,
    CAPTCHASONIC_EXT_PATH,
    NOPECHA_EXT_PATH,
    BIT_SOLVER_DIR,
    SOCIAL_DOMAINS,
)
from src.models import BusinessLead
from src.utils import (
    clean_url,
    clean_phone,
    extract_coordinates,
    parse_address_components,
    deduplicate_leads,
    extract_social_links,
    parse_proxy_string,
    load_proxies_from_file,
    ProxyManager,
    parse_review_count,
)

# ── Bit Solver config paths ────────────────────────────────────────────────────
_BIT_SOLVER_CONFIG   = os.path.join(BIT_SOLVER_DIR, "config.json")
_CAPTCHASONIC_CONFIG = os.path.join(CAPTCHASONIC_EXT_PATH, "config", "defaultConfig.json")
_NOPECHA_MANIFEST    = os.path.join(NOPECHA_EXT_PATH, "manifest.json")



class GoogleMapsScraper:
    """Robust Playwright scraper for Google Maps with Proxy Rotation and Captcha Solving."""

    def __init__(
        self,
        headless: bool = True,
        delay: float = 1.0,
        proxy: Optional[str] = None,
        proxy_file: Optional[str] = None,
        enable_captcha_solver: bool = False,
        solver_ext: str = "captchasonic",
        solver_path: Optional[str] = None,
    ):
        self.headless = headless
        self.delay = delay
        self.enable_captcha_solver = enable_captcha_solver
        self.solver_ext = solver_ext
        self.solver_path = solver_path

        # Setup Proxy Manager
        self.proxy_manager = ProxyManager()
        if proxy:
            self.proxy_manager.add_proxies([proxy])
        if proxy_file:
            file_proxies = load_proxies_from_file(proxy_file)
            self.proxy_manager.add_proxies(file_proxies)

    def _resolve_solver_extension_path(self) -> Optional[str]:
        """Resolve the directory path for the selected Captcha solver extension."""
        if self.solver_path and os.path.isdir(self.solver_path):
            return self.solver_path
        if self.solver_ext.lower() == "nopecha":
            return NOPECHA_EXT_PATH if os.path.isdir(NOPECHA_EXT_PATH) else None
        return CAPTCHASONIC_EXT_PATH if os.path.isdir(CAPTCHASONIC_EXT_PATH) else None

    async def _dismiss_consent(self, page: Page):
        """Bypass and dismiss Google cookie / consent dialogs if displayed."""
        consent_selectors = [
            'button[aria-label*="Accept all"]',
            'button[aria-label*="Reject all"]',
            'button:has-text("Accept all")',
            'button:has-text("I agree")',
            'button:has-text("Agree")',
            'button:has-text("Tout accepter")',
            'button:has-text("Alle akzeptieren")',
            'form[action*="consent"] button',
        ]
        for sel in consent_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=1500):
                    await btn.click()
                    await page.wait_for_timeout(1000)
                    break
            except Exception:
                pass

    async def _handle_captcha_if_present(
        self,
        page: Page,
        original_url: str,
        max_wait_sec: int = 120,
    ) -> bool:
        """
        Detect a Google CAPTCHA / unusual-traffic wall and wait for the Bit Solver
        extension to solve it transparently.

        Flow:
          1. Detect: URL contains ``/sorry/index``, page title says "unusual traffic",
             or a reCAPTCHA iframe/form is visible.
          2. If no CAPTCHA → return True immediately (nothing to do).
          3. If CAPTCHA but solver is disabled → return False (caller skips the lead).
          4. If solver is enabled:
               • Poll every 2 s — the extension works in the background and
                 submits the solution; Google then redirects back to the original URL.
               • Every 20 s of silence → reload the page so the extension gets a
                 fresh DOM to interact with (avoids stale iframe issues).
               • If still stuck after ``max_wait_sec`` → return False (lead skipped).
          5. On success (URL no longer a sorry page) → navigate back to ``original_url``
             and return True so the caller can retry the normal scrape flow.

        Args:
            page:           The Playwright page to check.
            original_url:   The Maps URL we were trying to load before the CAPTCHA.
            max_wait_sec:   Maximum seconds to wait for the extension to solve it
                            (default 120 s — extensions can take 30-60 s for reCAPTCHA).
        """
        def _is_captcha_url(url: str) -> bool:
            return "google.com/sorry/index" in url or "/sorry/index" in url

        async def _is_captcha_page(pg: Page) -> bool:
            try:
                url   = pg.url
                title = (await pg.title()).lower()
                recaptcha_visible = await pg.locator(
                    'iframe[src*="recaptcha"], div.g-recaptcha, #captcha-form'
                ).count() > 0
                return _is_captcha_url(url) or "unusual traffic" in title or recaptcha_visible
            except Exception:
                return False

        if not await _is_captcha_page(page):
            return True  # ✅ clean page, nothing to do

        if not self.enable_captcha_solver:
            # No solver — skip this page rather than hanging forever
            return False

        print(f"  [CAPTCHA] Detected on {page.url[:60]}… — waiting for Bit Solver extension…")

        poll_interval   = 2.0   # seconds between polls
        reload_every    = 20.0  # reload page every N seconds if still stuck
        elapsed         = 0.0
        since_last_reload = 0.0

        while elapsed < max_wait_sec:
            await asyncio.sleep(poll_interval)
            elapsed           += poll_interval
            since_last_reload += poll_interval

            if not await _is_captcha_page(page):
                # Extension solved it — redirect back to Maps
                print(f"  [CAPTCHA] ✅ Solved after {elapsed:.0f}s — resuming…")
                try:
                    await page.goto(original_url, wait_until="domcontentloaded", timeout=15000)
                    await asyncio.sleep(1.5)
                except Exception:
                    pass
                return True

            # Periodic page reload keeps the extension's iframe fresh
            if since_last_reload >= reload_every:
                since_last_reload = 0.0
                print(f"  [CAPTCHA] Still solving ({elapsed:.0f}s elapsed) — reloading page to refresh extension…")
                try:
                    await page.reload(wait_until="domcontentloaded", timeout=15000)
                    await asyncio.sleep(2.0)
                except Exception:
                    pass

        print(f"  [CAPTCHA] ⚠️  Timed out after {max_wait_sec}s — skipping page.")
        return False

    async def scrape_query(
        self,
        query: str,
        limit: int = 20,
        lead_callback: Optional[Callable[[BusinessLead], None]] = None,
    ) -> List[BusinessLead]:
        """
        Scrape Google Maps for a given search query with proxy and CAPTCHA support.
        
        Args:
            query: Search query (e.g. "Roofers in Miami, FL")
            limit: Maximum results to scrape (0 for unlimited)
            lead_callback: Optional callback invoked when each lead is extracted
        """
        leads: List[BusinessLead] = []
        user_agent = random.choice(DEFAULT_USER_AGENTS)
        active_proxy = self.proxy_manager.get_next_proxy()

        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ]

        # Build the Maps URL early so we can pass it to the captcha handler
        encoded_query = quote_plus(query)
        maps_url = f"https://www.google.com/maps/search/{encoded_query}?hl=en"

        async with async_playwright() as p:
            # When loading Chrome extensions, Playwright requires a persistent context.
            # _prepare_solver_extension copies the extension, injects the license key,
            # and enables RECAPTCHA2/hCaptcha auto-solve before the browser starts.
            if self.enable_captcha_solver:
                temp_user_data = tempfile.mkdtemp(prefix="gmaps_solver_")
                ext_path = self._prepare_solver_extension(temp_user_data)
                if ext_path:
                    launch_args.extend([
                        f"--disable-extensions-except={ext_path}",
                        f"--load-extension={ext_path}",
                    ])
                context = await p.chromium.launch_persistent_context(
                    user_data_dir=temp_user_data,
                    headless=False,   # extensions require a visible browser
                    args=launch_args,
                    proxy=active_proxy,
                    user_agent=user_agent,
                    viewport={"width": 1280, "height": 800},
                    locale="en-US",
                )
                page = context.pages[0] if context.pages else await context.new_page()
            else:
                browser = await p.chromium.launch(
                    headless=self.headless,
                    args=launch_args,
                    proxy=active_proxy,
                )
                context = await browser.new_context(
                    user_agent=user_agent,
                    viewport={"width": 1280, "height": 800},
                    locale="en-US",
                )
                page = await context.new_page()

            page.set_default_timeout(DEFAULT_TIMEOUT_MS)

            try:
                await page.goto(maps_url, wait_until="domcontentloaded")
                await self._dismiss_consent(page)
                # Pass the target URL so the handler can navigate back after solving
                solved = await self._handle_captcha_if_present(page, original_url=maps_url)
                if not solved and self.enable_captcha_solver:
                    # If CAPTCHA timed out, abort this query cleanly
                    await context.close()
                    return leads
                await page.wait_for_timeout(2500)


                # Find the feed container
                feed_selector = 'div[role="feed"]'
                try:
                    await page.wait_for_selector(feed_selector, timeout=8000)
                except Exception:
                    if await page.locator('h1').first.is_visible(timeout=3000):
                        single_lead = BusinessLead(search_query=query, google_maps_url=page.url)
                        await self._extract_place_page_details(page, single_lead)
                        if single_lead.name:
                            leads.append(single_lead)
                            if lead_callback:
                                if asyncio.iscoroutinefunction(lead_callback):
                                    await lead_callback(single_lead)
                                else:
                                    lead_callback(single_lead)
                        await context.close()
                        return leads

                # Phase 1: Scroll feed and collect all item cards
                seen_place_urls = set()
                scroll_attempts = 0
                max_scroll_attempts = 40

                while scroll_attempts < max_scroll_attempts:
                    current_links = await page.locator('div[role="feed"] a[href*="/maps/place/"]').all()
                    for link in current_links:
                        try:
                            href = await link.get_attribute("href")
                            if href:
                                seen_place_urls.add(href)
                        except Exception:
                            pass

                    if limit > 0 and len(seen_place_urls) >= limit:
                        break

                    # Scroll down
                    try:
                        feed = page.locator(feed_selector)
                        await feed.evaluate("el => el.scrollBy(0, 1200)")
                        await asyncio.sleep(DEFAULT_SCROLL_PAUSE + random.uniform(0.1, 0.4))
                    except Exception:
                        break

                    # Check for end of list
                    end_text = page.locator('text="You\'ve reached the end of the list."').first
                    if await end_text.is_visible(timeout=400):
                        break

                    scroll_attempts += 1

                # Extract initial basic card metadata from feed
                feed_cards = await page.locator('div[role="feed"] > div:has(a[href*="/maps/place/"])').all()
                if not feed_cards:
                    feed_cards = await page.locator('div[role="feed"] a[href*="/maps/place/"]').all()

                for card in feed_cards:
                    try:
                        # Determine if card is an <a> tag itself or contains one
                        tag_name = await card.evaluate("el => el.tagName.toLowerCase()")
                        if tag_name == "a":
                            link_el = card
                        else:
                            link_el = card.locator('a[href*="/maps/place/"]').first
                            if not await link_el.is_visible(timeout=200):
                                continue

                        href = await link_el.get_attribute("href") or ""
                        if not href or any(l.google_maps_url == href for l in leads):
                            continue

                        name = (await link_el.get_attribute("aria-label")) or ""
                        if not name:
                            title_el = card.locator('div.fontHeadlineSmall, div.qBF1Pd').first
                            if await title_el.count() > 0:
                                name = (await title_el.inner_text()).strip()

                        # If name still empty, parse from first line of card text
                        if not name:
                            raw_t = (await card.inner_text()).split("\n")
                            name = raw_t[0].strip() if raw_t else "Unknown Business"

                        # Card rating & reviews
                        rating = None
                        review_count = None
                        rating_el = card.locator('span.MW4etd').first
                        if await rating_el.is_visible(timeout=100):
                            try:
                                rating = float((await rating_el.inner_text()).strip())
                            except ValueError:
                                pass

                        # Multi-selector review count extraction
                        reviews_selectors = [
                            'span.UY7F9',
                            'span.R48cEc',
                            'span.e4rVHe',
                            'span.ZDu9vd',
                            'span[aria-label*="review" i]',
                        ]
                        for sel in reviews_selectors:
                            r_el = card.locator(sel).first
                            if await r_el.count() > 0 and await r_el.is_visible(timeout=50):
                                r_text = (await r_el.get_attribute("aria-label")) or (await r_el.inner_text()) or ""
                                val = parse_review_count(r_text)
                                if val is not None:
                                    review_count = val
                                    break

                        # Fallback: check card text for "(123)"
                        if review_count is None:
                            card_text = await card.inner_text()
                            review_count = parse_review_count(card_text)

                        # Create lead immediately with card metadata
                        lead = BusinessLead(
                            name=name,
                            rating=rating,
                            review_count=review_count,
                            google_maps_url=href,
                            search_query=query,
                        )
                        lat, lng = extract_coordinates(href)
                        lead.latitude = lat
                        lead.longitude = lng

                        # Fast card-level website extraction if present
                        card_web = card.locator('a[data-value="Website"], a[aria-label*="Website" i]').first
                        if await card_web.count() > 0 and await card_web.is_visible(timeout=50):
                            lead.website = await card_web.get_attribute("href")

                        # Append to leads right away so leads are NEVER lost
                        leads.append(lead)

                        # Fire live telemetry callback immediately upon card discovery
                        if lead_callback:
                            try:
                                if asyncio.iscoroutinefunction(lead_callback):
                                    await lead_callback(lead)
                                else:
                                    lead_callback(lead)
                            except Exception:
                                pass

                        if limit > 0 and len(leads) >= limit:
                            break
                    except Exception:
                        continue

                # Phase 2: High-fidelity deep detail extraction by navigating place pages
                # Snappy 6s timeout so a single slow place page never blocks the pipeline
                detail_page = await context.new_page()
                detail_page.set_default_timeout(6000)

                for lead in leads:
                    try:
                        await detail_page.goto(lead.google_maps_url, wait_until="domcontentloaded", timeout=6000)
                        await self._handle_captcha_if_present(detail_page)
                        await detail_page.wait_for_timeout(min(int(self.delay * 500), 500))
                        await self._extract_place_page_details(detail_page, lead)
                    except Exception:
                        pass

                await detail_page.close()

            except Exception:
                pass
            finally:
                await context.close()

        return deduplicate_leads(leads)

    async def _extract_place_page_details(self, page: Page, lead: BusinessLead):
        """Extract all structured business attributes from an active place detail page."""
        try:
            # 1. Full Business Name
            h1_el = page.locator('div[role="main"] h1, h1.DUwDvf').first
            if await h1_el.count() > 0:
                name_text = (await h1_el.inner_text()).strip()
                if name_text:
                    lead.name = name_text

            # 2. Primary Category
            cat_el = page.locator('button[jsaction*="category"], button.DkEaL').first
            if await cat_el.count() > 0:
                lead.category = (await cat_el.inner_text()).strip()

            # 3. Full Address
            addr_el = page.locator('button[data-item-id="address"], button[aria-label*="Address:"]').first
            if await addr_el.count() > 0:
                raw_addr = await addr_el.get_attribute("aria-label") or ""
                addr_text = raw_addr.replace("Address: ", "").strip()
                if not addr_text:
                    addr_text = (await addr_el.inner_text()).replace("", "").strip()
                
                lead.address = addr_text
                comp = parse_address_components(addr_text)
                lead.street = comp.get("street")
                lead.city = comp.get("city")
                lead.state = comp.get("state")
                lead.postal_code = comp.get("postal_code")
                lead.country = comp.get("country")

            # 4. Phone Number
            phone_el = page.locator('button[data-item-id^="phone:"], button[aria-label*="Phone:"]').first
            if await phone_el.count() > 0:
                raw_phone = await phone_el.get_attribute("aria-label") or ""
                phone_text = raw_phone.replace("Phone: ", "").strip()
                if not phone_text:
                    phone_text = (await phone_el.inner_text()).replace("", "").strip()
                lead.phone = clean_phone(phone_text)

            # 5. Website
            web_el = page.locator('a[data-item-id="authority"], a[aria-label*="Website:"]').first
            if await web_el.count() > 0:
                web_href = await web_el.get_attribute("href")
                cleaned_w = clean_url(web_href)
                # Check if the "website" link is actually a social media page (e.g. facebook.com/page, instagram.com/page).
                # Many small businesses without a real website list their Facebook page in the website field.
                is_social_page = False
                if cleaned_w:
                    for platform, domains in SOCIAL_DOMAINS.items():
                        if any(d in cleaned_w.lower() for d in domains):
                            setattr(lead, platform, cleaned_w)
                            is_social_page = True
                            break
                if not is_social_page:
                    lead.website = cleaned_w
                else:
                    lead.website = None  # Flagged as social contact, NO custom website (prime web design lead!)

            # 6. Rating & Reviews
            if lead.rating is None:
                rating_el = page.locator('div[role="main"] span[aria-label*="stars"]').first
                if await rating_el.count() > 0:
                    raw_stars = await rating_el.get_attribute("aria-label") or ""
                    match = re.search(r"(\d+\.\d+)", raw_stars)
                    if match:
                        lead.rating = float(match.group(1))

            if lead.review_count is None:
                detail_selectors = [
                    'div[role="main"] button[aria-label*="review" i]',
                    'div[role="main"] span[aria-label*="review" i]',
                    'div[role="main"] span.F7nice span:last-child',
                    'div[role="main"] span.F7nice',
                    'div[role="main"] button.HHrUdb',
                    'div[role="main"] button:has-text("reviews")',
                ]
                for sel in detail_selectors:
                    rev_el = page.locator(sel).first
                    if await rev_el.count() > 0:
                        raw_rev = (await rev_el.get_attribute("aria-label")) or (await rev_el.inner_text()) or ""
                        val = parse_review_count(raw_rev)
                        if val is not None:
                            lead.review_count = val
                            break

            # 7. Operating Hours / Status
            hours_el = page.locator('div[data-item-id="oh"], span.ZDu9vd, div.t39EBf').first
            if await hours_el.count() > 0:
                lead.status = (await hours_el.inner_text()).split("\n")[0].strip()

            # 8. Price Level
            price_el = page.locator('span[aria-label*="Price:"]').first
            if await price_el.count() > 0:
                lead.price_level = (await price_el.inner_text()).strip()

            # 9. Claimed Status
            claim_count = await page.locator('a[aria-label*="Claim this business"], button[aria-label*="Claim this business"]').count()
            lead.is_claimed = (claim_count == 0)

            # 10. Update coordinates if needed
            if not lead.latitude or not lead.longitude:
                lat, lng = extract_coordinates(page.url)
                if lat and lng:
                    lead.latitude = lat
                    lead.longitude = lng

            # 11. Extract social profiles & direct emails directly from the Google Maps detail page
            try:
                page_html = await page.content()
                page_socials = extract_social_links(page_html)
                for platform, link in page_socials.items():
                    if link and not getattr(lead, platform, None):
                        setattr(lead, platform, link)

                # Extract any direct mailto links in the listing
                mailto_matches = re.findall(r'mailto:([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)', page_html)
                for m in mailto_matches:
                    clean_m = m.lower().strip()
                    if clean_m not in lead.emails:
                        lead.emails.append(clean_m)
                if not lead.primary_email and lead.emails:
                    lead.primary_email = lead.emails[0]
            except Exception:
                pass

        except Exception:
            pass

