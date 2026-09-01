"""
Ollama AI Lead Intelligence Processor:
Leverages local Ollama models (e.g. qwen2.5vl:7b, qwen3.8:27b, llama3.1, etc.) to:
  1. Filter out junk/spam listings (permanently closed, aggregators, government, test entries).
  2. Normalize and clean spammy business names and categories.
  3. Score lead viability (1-10) for B2B and web design outreach.
  4. Generate custom 1-sentence sales pitch angles for outreach.
"""
import asyncio
import json
import logging
import re
from typing import List, Dict, Any, Optional, Tuple, Callable
import aiohttp
import requests

from src.models import BusinessLead

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_ENDPOINT = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "bit:latest"


class OllamaClient:
    """High-performance client for local Ollama LLM / VLM instances."""

    def __init__(
        self,
        endpoint: str = DEFAULT_OLLAMA_ENDPOINT,
        model: str = DEFAULT_OLLAMA_MODEL,
        timeout_sec: int = 90,
        concurrency: int = 3,
    ):
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.timeout_sec = timeout_sec
        self.concurrency = max(1, concurrency)
        self.semaphore = asyncio.Semaphore(self.concurrency)

    @staticmethod
    def check_connection_sync(endpoint: str = DEFAULT_OLLAMA_ENDPOINT) -> Tuple[bool, List[str], str]:
        """Synchronously probe Ollama API tags to check availability and list local models."""
        url = f"{endpoint.rstrip('/')}/api/tags"
        try:
            resp = requests.get(url, timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
                return True, models, f"Online ({len(models)} models available)"
            return False, [], f"HTTP {resp.status_code}"
        except Exception as e:
            return False, [], f"Offline ({str(e)[:30]})"

    async def check_connection(self) -> Tuple[bool, List[str], str]:
        """Asynchronously probe Ollama API tags."""
        url = f"{self.endpoint}/api/tags"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=4)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        models = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
                        return True, models, f"Online ({len(models)} models available)"
                    return False, [], f"HTTP {resp.status}"
        except Exception as e:
            return False, [], f"Offline ({str(e)[:30]})"

    async def _query_model_json(
        self,
        session: aiohttp.ClientSession,
        prompt: str,
        system: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Query Ollama with JSON format enforcement via /api/chat with /api/generate fallback."""
        chat_url = f"{self.endpoint}/api/chat"
        chat_payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system or "You are an expert B2B lead analyst. Output strictly valid JSON."},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.1,
                "top_p": 0.9,
            },
        }

        try:
            async with session.post(
                chat_url,
                json=chat_payload,
                timeout=aiohttp.ClientTimeout(total=self.timeout_sec),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    msg_content = data.get("message", {}).get("content", "")
                    if msg_content:
                        try:
                            return json.loads(msg_content)
                        except json.JSONDecodeError:
                            match = re.search(r"(\{.*\})", msg_content, re.DOTALL)
                            if match:
                                return json.loads(match.group(1))
        except Exception:
            pass

        # Fallback to /api/generate
        gen_url = f"{self.endpoint}/api/generate"
        gen_payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1},
        }

        try:
            async with session.post(
                gen_url,
                json=gen_payload,
                timeout=aiohttp.ClientTimeout(total=self.timeout_sec),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    raw_response = data.get("response", "")
                    try:
                        return json.loads(raw_response)
                    except json.JSONDecodeError:
                        match = re.search(r"(\{.*\})", raw_response, re.DOTALL)
                        if match:
                            return json.loads(match.group(1))
        except Exception as e:
            logger.warning(f"Ollama query failed on {self.model}: {e}")

        return None

    def _build_lead_prompt(self, lead: BusinessLead) -> str:
        """Construct structured prompt for analyzing a single business lead."""
        website_status = "None (No Website)" if not lead.has_website else lead.website
        contacts = []
        if lead.has_phone:
            contacts.append(f"Phone: {lead.phone}")
        if lead.has_email:
            contacts.append(f"Email: {lead.primary_email or ', '.join(lead.emails)}")
        if lead.has_social:
            contacts.append(f"Socials: {lead.contact_channels}")
        contacts_str = "; ".join(contacts) if contacts else "None found"

        return f"""Analyze this Google Maps business listing for B2B & Web Design prospecting:

- Business Name: {lead.name}
- Category: {lead.category or 'Unknown'}
- Location: {lead.address or lead.city or 'Unknown'}
- Rating: {lead.rating if lead.rating is not None else 'N/A'} ({lead.review_count or 0} reviews)
- Website: {website_status}
- Contact Channels: {contacts_str}
- Search Query: {lead.search_query}

Evaluate and return a JSON object with EXACTLY these keys:
{{
  "is_junk": boolean (true if listing is permanently closed, spam keyword stuffing, government/police/hospital for commercial B2B, directory aggregator, or invalid),
  "junk_reason": string or null (brief explanation if is_junk is true, else null),
  "cleaned_name": string (clean business name with SEO keyword stuffing / promotional words removed, e.g. "Katroz Gaming Cafe 24/7 Best" -> "Katroz Gaming Cafe"),
  "cleaned_category": string (concise primary business category),
  "lead_score": integer 1-10 (1=useless/junk, 5=average, 10=hottest prospect with high reviews + phone but no website),
  "pitch_angle": string (1 punchy sentence explaining why this business needs a new website or web upgrade and how to pitch them),
  "summary": string (1 concise sentence describing what this business does)
}}"""

    async def analyze_lead(
        self,
        lead: BusinessLead,
        session: aiohttp.ClientSession,
    ) -> BusinessLead:
        """Analyze, score, clean, and filter a single lead with local Ollama AI."""
        system_prompt = (
            "You are an expert B2B lead generation analyst and web design strategist. "
            "You analyze business directory data to filter spam, sanitize names, score lead quality, "
            "and identify high-converting cold outreach angles. Output strictly valid JSON."
        )
        prompt = self._build_lead_prompt(lead)

        async with self.semaphore:
            res = await self._query_model_json(session, prompt, system=system_prompt)
            if res and isinstance(res, dict):
                lead.ai_is_junk = bool(res.get("is_junk", False))
                lead.ai_junk_reason = res.get("junk_reason")
                if res.get("cleaned_name"):
                    lead.ai_cleaned_name = str(res.get("cleaned_name")).strip()
                if res.get("cleaned_category"):
                    lead.ai_cleaned_category = str(res.get("cleaned_category")).strip()
                
                # Parse lead score
                score_raw = res.get("lead_score")
                if score_raw is not None:
                    try:
                        score_val = int(score_raw)
                        lead.ai_lead_score = max(1, min(10, score_val))
                    except (ValueError, TypeError):
                        pass

                if res.get("pitch_angle"):
                    lead.ai_pitch_angle = str(res.get("pitch_angle")).strip()
                if res.get("summary"):
                    lead.ai_summary = str(res.get("summary")).strip()
            else:
                # Heuristic fallback if model times out or returns unparseable output
                self._apply_heuristic_scoring(lead)

        return lead

    def _apply_heuristic_scoring(self, lead: BusinessLead) -> None:
        """Fallback rule-based scoring if Ollama model is offline or skipped."""
        score = 5
        # No website is huge plus for web builders
        if not lead.has_website:
            score += 3
        # Has reviews -> active business
        if lead.review_count and lead.review_count >= 10:
            score += 1
        # Has phone or email -> contactable
        if lead.has_phone or lead.has_email:
            score += 1
        lead.ai_lead_score = max(1, min(10, score))
        if not lead.has_website and lead.has_phone:
            lead.ai_pitch_angle = (
                f"Has {lead.review_count or 'active'} reviews on Google Maps with direct phone contact, "
                f"but no website to capture and convert incoming search leads."
            )

    async def process_leads_batch(
        self,
        leads: List[BusinessLead],
        progress_callback: Optional[Callable[[BusinessLead, int, int], None]] = None,
        filter_junk: bool = False,
    ) -> List[BusinessLead]:
        """
        Process a list of leads concurrently through Ollama.
        
        Args:
            leads: List of BusinessLead objects
            progress_callback: Callback receiving (lead, completed_count, total_count)
            filter_junk: If True, exclude leads flagged as `ai_is_junk`
            
        Returns:
            List of AI-enriched BusinessLead objects (with optional junk filtering applied).
        """
        if not leads:
            return []

        total = len(leads)
        completed = 0
        lock = asyncio.Lock()

        async with aiohttp.ClientSession() as session:
            async def _worker(lead: BusinessLead):
                nonlocal completed
                res = await self.analyze_lead(lead, session)
                async with lock:
                    completed += 1
                    if progress_callback:
                        try:
                            if asyncio.iscoroutinefunction(progress_callback):
                                await progress_callback(res, completed, total)
                            else:
                                progress_callback(res, completed, total)
                        except Exception:
                            pass
                return res

            tasks = [_worker(lead) for lead in leads]
            enriched_leads = await asyncio.gather(*tasks)

        if filter_junk:
            return [l for l in enriched_leads if not l.ai_is_junk]

        return list(enriched_leads)
