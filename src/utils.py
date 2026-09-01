"""
Utility helper functions for data parsing, URL cleansing, coordinates extraction, and deduplication.
"""
import json
import os
import re
import secrets
import string
from typing import List, Optional, Tuple, Set, Dict, Any
from urllib.parse import urlparse, parse_qs, unquote
from src.config import JUNK_EMAIL_PATTERNS, SOCIAL_DOMAINS, PROXY_CONFIG_FILE, SIDEBAR_CONFIG_FILE, SESSION_CHECKPOINT_FILE


# RFC-5322 compatible regex for capturing email addresses
EMAIL_REGEX = re.compile(
    r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
    re.IGNORECASE
)

# Regex to extract coordinates from Google Maps URLs
# Format 1: /@37.7749295,-122.4194155,15z
COORD_PATTERN_1 = re.compile(r"@(-?\d+\.\d+),(-?\d+\.\d+)")
# Format 2: !3d37.7749295!4d-122.4194155
COORD_PATTERN_2 = re.compile(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)")


def clean_url(url: Optional[str]) -> Optional[str]:
    """Clean and resolve redirect URLs (like Google redirect wrappers)."""
    if not url:
        return None

    url = url.strip()
    # Check if it's a Google redirect wrapper (e.g. /url?q=https://example.com)
    if "google.com/url?" in url:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        if "q" in params:
            url = params["q"][0]
        elif "url" in params:
            url = params["url"][0]

    # Ensure http/https scheme
    if not url.startswith("http://") and not url.startswith("https://"):
        if url.startswith("//"):
            url = "https:" + url
        else:
            url = "https://" + url

    # Remove trailing tracking params
    try:
        parsed = urlparse(url)
        # Keep clean domain + path
        cleaned = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if parsed.query and not any(k in parsed.query for k in ["utm_", "fbclid", "gclid"]):
            cleaned += f"?{parsed.query}"
        return cleaned.rstrip("/")
    except Exception:
        return url


def extract_coordinates(url: str) -> Tuple[Optional[float], Optional[float]]:
    """Extract latitude and longitude from a Google Maps URL."""
    if not url:
        return None, None

    match1 = COORD_PATTERN_1.search(url)
    if match1:
        try:
            return float(match1.group(1)), float(match1.group(2))
        except ValueError:
            pass

    match2 = COORD_PATTERN_2.search(url)
    if match2:
        try:
            return float(match2.group(1)), float(match2.group(2))
        except ValueError:
            pass

    return None, None


def clean_phone(phone: Optional[str]) -> Optional[str]:
    """Format and normalize phone numbers."""
    if not phone:
        return None
    cleaned = phone.strip()
    # Remove leading non-digit except '+' or '('
    cleaned = re.sub(r"^[^\d+(]+", "", cleaned)
    cleaned = re.sub(r"[^\d)]+$", "", cleaned)
    return cleaned if len(re.sub(r"\D", "", cleaned)) >= 6 else None

def parse_review_count(text: Optional[str]) -> Optional[int]:
    """
    Parse review count from any Google Maps review string format.
    Supports:
      - "(142)" or "(1,234)"
      - "142 reviews" or "1 review" or "1,240 Reviews"
      - "2.5K reviews" or "1.2k"
      - "4.8 stars 95 reviews"
      - Raw isolated review digits like "95" or "1,240"
    """
    if not text:
        return None
    text = text.strip()

    # 1. Match "1.4K reviews" or "2.5k"
    k_match = re.search(r"([\d.]+)\s*[kK]\s*(?:reviews?|ratings?|bewertungen|avis)?\b", text, re.IGNORECASE)
    if k_match:
        try:
            val = int(float(k_match.group(1)) * 1000)
            if val < 10_000_000:
                return val
        except ValueError:
            pass

    # 2. Match "(1,234)" or "(123)"
    paren_match = re.search(r"\(([\d,]+)\)", text)
    if paren_match:
        digits = paren_match.group(1).replace(",", "")
        if digits.isdigit() and int(digits) < 10_000_000:
            return int(digits)

    # 3. Match "1,234 reviews" or "12 reviews" or "1 review" or "4.8 stars 95 reviews"
    word_match = re.search(r"([\d,]+)\s+(?:reviews?|ratings?|bewertungen|avis|reseñas|recensioni)\b", text, re.IGNORECASE)
    if word_match:
        digits = word_match.group(1).replace(",", "")
        if digits.isdigit() and int(digits) < 10_000_000:
            return int(digits)

    # 4. If the string is short and isolated digits (e.g. dedicated review badge)
    clean_isolated = text.replace(",", "").strip()
    if clean_isolated.isdigit() and len(clean_isolated) <= 6:
        val = int(clean_isolated)
        if 0 <= val <= 2_000_000:
            return val

    return None


def parse_address_components(address: Optional[str]) -> Dict[str, Optional[str]]:
    """
    Attempt to extract street, city, state, postal code, and country from address strings.
    Handles standard US and international comma-separated address structures.
    """
    res = {
        "street": None,
        "city": None,
        "state": None,
        "postal_code": None,
        "country": None,
    }
    if not address:
        return res

    parts = [p.strip() for p in address.split(",") if p.strip()]
    if not parts:
        return res

    # Simple heuristic for US/Standard addresses
    # Example: "123 Main St, Austin, TX 78701, USA"
    if len(parts) >= 3:
        res["street"] = parts[0]
        res["city"] = parts[1]
        
        # State + Zip part, e.g. "TX 78701" or "NY 10001" or "ON M5V 2T6"
        state_zip = parts[2]
        zip_match = re.search(r"(\b[A-Z]{2}\b)?\s*(\b\d{5}(?:-\d{4})?\b|\b[A-Z\d]{3}\s?[A-Z\d]{3}\b)", state_zip)
        if zip_match:
            res["state"] = zip_match.group(1)
            res["postal_code"] = zip_match.group(2)
        else:
            res["state"] = state_zip

        if len(parts) >= 4:
            res["country"] = parts[3]
    elif len(parts) == 2:
        res["street"] = parts[0]
        res["city"] = parts[1]
    else:
        res["street"] = address

    return res


def extract_valid_emails(html_text: str) -> List[str]:
    """Extract, deduplicate, and validate email addresses from raw text/HTML."""
    raw_emails = EMAIL_REGEX.findall(html_text)
    valid_emails = []
    seen = set()

    for email in raw_emails:
        email = email.lower().strip(".,;:()<>[]\"' ")
        if not email or email in seen:
            continue

        # Filter out junk extensions or known false positives
        is_junk = False
        for pattern in JUNK_EMAIL_PATTERNS:
            if re.search(pattern, email, re.IGNORECASE):
                is_junk = True
                break

        if is_junk:
            continue

        # Basic validity check (needs a valid TLD with at least 2 chars)
        parts = email.split("@")
        if len(parts) == 2 and "." in parts[1]:
            domain = parts[1]
            tld = domain.split(".")[-1]
            if len(tld) >= 2 and not tld.isdigit():
                valid_emails.append(email)
                seen.add(email)

    return valid_emails


def extract_social_links(html_text: str, base_url: str = "") -> Dict[str, Optional[str]]:
    """Extract social media profile URLs from HTML content."""
    socials: Dict[str, Optional[str]] = {
        "linkedin": None,
        "facebook": None,
        "instagram": None,
        "twitter": None,
        "youtube": None,
        "tiktok": None,
        "pinterest": None,
    }

    # Find all href links
    href_matches = re.findall(r'href=[\'"]([^\'"]+)[\'"]', html_text, re.IGNORECASE)
    
    for href in href_matches:
        href_clean = href.strip()
        for platform, domains in SOCIAL_DOMAINS.items():
            if socials[platform] is not None:
                continue
            for domain in domains:
                if domain in href_clean.lower():
                    # Filter out share buttons / intent links
                    if "sharer" in href_clean or "intent/tweet" in href_clean or "shareArticle" in href_clean:
                        continue
                    if not href_clean.startswith("http"):
                        href_clean = "https://" + href_clean.lstrip("/")
                    socials[platform] = href_clean
                    break

    return socials


def parse_proxy_string(proxy_str: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Parse various proxy string formats into Playwright / aiohttp compatible configuration.
    
    Supported formats:
      - http://username:password@host:port
      - socks5://username:password@host:port
      - host:port:username:password
      - host:port
      - http://host:port
    """
    if not proxy_str or not proxy_str.strip():
        return None

    proxy_str = proxy_str.strip()

    # Format: host:port:username:password
    if "://" not in proxy_str and proxy_str.count(":") == 3:
        parts = proxy_str.split(":")
        return {
            "server": f"http://{parts[0]}:{parts[1]}",
            "username": parts[2],
            "password": parts[3],
        }

    # Format: host:port
    if "://" not in proxy_str and proxy_str.count(":") == 1:
        return {
            "server": f"http://{proxy_str}",
        }

    # Standard URL format http://user:pass@host:port
    try:
        parsed = urlparse(proxy_str)
        scheme = parsed.scheme or "http"
        host = parsed.hostname
        port = parsed.port
        username = unquote(parsed.username) if parsed.username else None
        password = unquote(parsed.password) if parsed.password else None

        if not host:
            return None

        server = f"{scheme}://{host}"
        if port:
            server += f":{port}"

        res = {"server": server}
        if username:
            res["username"] = username
        if password:
            res["password"] = password
        return res
    except Exception:
        return {"server": proxy_str}


def to_proxy_url(proxy_str: Optional[str]) -> Optional[str]:
    """
    Convert any supported proxy string format into a standard URL format
    (e.g., http://user:pass@host:port or http://host:port) suitable for HTTP clients like aiohttp.
    """
    cfg = parse_proxy_string(proxy_str)
    if not cfg:
        return None
    server = cfg.get("server", "")
    username = cfg.get("username")
    password = cfg.get("password")
    if username and password:
        if "://" in server:
            scheme, netloc = server.split("://", 1)
            return f"{scheme}://{username}:{password}@{netloc}"
        return f"http://{username}:{password}@{server}"
    return server


def load_saved_proxy_config() -> Dict[str, Any]:
    """Load persisted proxy settings from disk."""
    default_config = {
        "mode": "Direct IP",
        "single_proxy": "",
        "rotating_proxies": "",
        "proxy_file_path": "",
    }
    if not os.path.exists(PROXY_CONFIG_FILE):
        return default_config
    try:
        with open(PROXY_CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return {
                "mode": data.get("mode", "Direct IP"),
                "single_proxy": data.get("single_proxy", ""),
                "rotating_proxies": data.get("rotating_proxies", ""),
                "proxy_file_path": data.get("proxy_file_path", ""),
            }
    except Exception:
        return default_config


def save_proxy_config(mode: str, single_proxy: str = "", rotating_proxies: str = "", proxy_file_path: str = "") -> None:
    """Save proxy configuration to disk so it persists across refreshes and restarts."""
    try:
        data = {
            "mode": mode,
            "single_proxy": single_proxy.strip(),
            "rotating_proxies": rotating_proxies.strip(),
            "proxy_file_path": proxy_file_path.strip(),
        }
        with open(PROXY_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def load_saved_sidebar_config() -> Dict[str, Any]:
    """Load persistent sidebar configuration from disk."""
    default_config = {
        "threads": 4,
        "limit": 15,
        "delay": 1.0,
        "enrich": True,
        "concurrency": 20,
        "headless": True,
        "use_solver": False,
        "solver_ext": "captchasonic",
        "proxy_mode": "Direct IP",
        "single_proxy": "",
        "rotating_proxies": "",
        "proxy_file_path": "",
        "enable_ai": True,
        "ollama_endpoint": "http://localhost:11434",
        "ollama_model": "qwen2.5vl:7b",
        "ai_filter_junk": True,
        "ai_concurrency": 6,
    }
    if not os.path.exists(SIDEBAR_CONFIG_FILE):
        return default_config
    try:
        with open(SIDEBAR_CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            merged = dict(default_config)
            merged.update(data)
            return merged
    except Exception:
        return default_config


def save_sidebar_config(config_dict: Dict[str, Any]) -> None:
    """Save full sidebar configuration to disk."""
    try:
        with open(SIDEBAR_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_dict, f, indent=2)
    except Exception:
        pass


def save_session_checkpoint(
    status: str,
    queries: List[str],
    completed_queries: List[str],
    pending_queries: List[str],
    leads: List[Any],
    config: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Save real-time scraping progress to disk so if the browser is refreshed,
    interrupted, or stopped, progress and leads are 100% preserved.
    """
    try:
        leads_dump = []
        for l in leads:
            if hasattr(l, "model_dump"):
                leads_dump.append(l.model_dump())
            elif isinstance(l, dict):
                leads_dump.append(l)

        payload = {
            "status": status,  # 'running', 'paused', 'completed'
            "queries": queries,
            "completed_queries": completed_queries,
            "pending_queries": pending_queries,
            "lead_count": len(leads_dump),
            "leads": leads_dump,
            "config": config or {},
        }
        with open(SESSION_CHECKPOINT_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except Exception:
        pass


def load_session_checkpoint() -> Optional[Dict[str, Any]]:
    """
    Load active session checkpoint from disk if one exists.
    Returns parsed dictionary or None.
    """
    if not os.path.exists(SESSION_CHECKPOINT_FILE):
        return None
    try:
        with open(SESSION_CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def clear_session_checkpoint() -> None:
    """Clear active session checkpoint file."""
    try:
        if os.path.exists(SESSION_CHECKPOINT_FILE):
            os.remove(SESSION_CHECKPOINT_FILE)
    except Exception:
        pass


def load_proxies_from_file(filepath: str) -> List[str]:
    """Load proxy strings from a text file (one per line, ignoring comments and blanks)."""
    if not filepath or not os.path.isfile(filepath):
        return []
    proxies = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            clean_l = line.strip()
            if clean_l and not clean_l.startswith("#"):
                proxies.append(clean_l)
    return proxies


def refresh_proxy_session(proxy_dict: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    If a proxy has a residential session-based username (e.g., mucasp14nztsykr-session-XXXXX-lifetime-5),
    generate a fresh random session ID so the proxy session never expires or throttles across workers.
    """
    if not proxy_dict or "username" not in proxy_dict:
        return proxy_dict

    username = proxy_dict.get("username") or ""
    # Check for session pattern: -session-<id> or _session_<id>
    if "-session-" in username or "_session_" in username:
        rand_id = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(10))
        new_username = re.sub(r"(-session-)[a-zA-Z0-9]+", rf"\g<1>{rand_id}", username, count=1)
        new_username = re.sub(r"(_session_)[a-zA-Z0-9]+", rf"\g<1>{rand_id}", new_username, count=1)
        res = dict(proxy_dict)
        res["username"] = new_username
        return res

    return proxy_dict


class ProxyManager:
    """Manages proxy rotation across requests with dynamic residential session support."""
    def __init__(self, proxies: Optional[List[str]] = None):
        self.proxies = proxies or []
        self._index = 0

    def add_proxies(self, proxies: List[str]):
        for p in proxies:
            if p and p not in self.proxies:
                self.proxies.append(p)

    def get_next_proxy(self, rotate_session: bool = True) -> Optional[Dict[str, Any]]:
        """Get the next proxy in round-robin sequence with dynamic session rotation."""
        if not self.proxies:
            return None
        proxy_str = self.proxies[self._index % len(self.proxies)]
        self._index += 1
        parsed = parse_proxy_string(proxy_str)
        if rotate_session and parsed:
            return refresh_proxy_session(parsed)
        return parsed

    def get_next_proxy_str(self, rotate_session: bool = True) -> Optional[str]:
        """Get the raw proxy string in round-robin sequence."""
        if not self.proxies:
            return None
        proxy_str = self.proxies[self._index % len(self.proxies)]
        self._index += 1
        if rotate_session and ("-session-" in proxy_str or "_session_" in proxy_str):
            parsed = refresh_proxy_session(parse_proxy_string(proxy_str))
            if parsed and parsed.get("username"):
                return to_proxy_url(f"{parsed['server'].replace('http://','')}:{parsed['username']}:{parsed.get('password','')}")
        return proxy_str

    def __len__(self):
        return len(self.proxies)


def extract_place_cid(maps_url: Optional[str]) -> Optional[str]:
    """Extract unique hex Place CID (!1s0x...:0x...) from Google Maps URL if present."""
    if not maps_url:
        return None
    match = re.search(r"!1s(0x[0-9a-fA-F]+:0x[0-9a-fA-F]+)", maps_url)
    return match.group(1).lower() if match else None


def get_lead_dedup_keys(lead: Any) -> List[str]:
    """
    Generate all possible unique identification keys for a lead.
    Matches across Place ID, CID, Phone, Name+Location, and Website.
    """
    keys = []
    
    # 1. Place ID
    if getattr(lead, "place_id", None):
        keys.append(f"place_id:{str(lead.place_id).strip()}")

    # 2. Hex CID from Maps URL
    maps_url = getattr(lead, "google_maps_url", "") or ""
    cid = extract_place_cid(maps_url)
    if cid:
        keys.append(f"cid:{cid}")

    # 3. Cleaned Phone Number (if at least 7 digits)
    phone = getattr(lead, "phone", None)
    if phone:
        clean_p = re.sub(r"\D", "", phone)
        if len(clean_p) >= 7:
            keys.append(f"phone:{clean_p}")

    # 4. Normalized Place Name + Location
    name = (getattr(lead, "name", "") or "").strip().lower()
    name_clean = re.sub(r"[^\w\s]", "", name)
    
    city = (getattr(lead, "city", "") or getattr(lead, "state", "") or "").strip().lower()
    addr = (getattr(lead, "address", "") or "").strip().lower()
    
    if name_clean:
        if city:
            keys.append(f"name_loc:{name_clean}:{city}")
        elif addr:
            first_addr = addr.split(",")[0].strip()
            keys.append(f"name_loc:{name_clean}:{first_addr}")
        else:
            keys.append(f"name:{name_clean}")

    # 5. Root Website Domain
    website = getattr(lead, "website", None)
    if website and "google.com" not in website.lower():
        try:
            parsed_w = urlparse(website)
            domain = parsed_w.netloc.lower().replace("www.", "")
            if domain and len(domain) >= 4:
                keys.append(f"domain:{domain}")
        except Exception:
            pass

    return keys


def merge_lead_attributes(target: Any, source: Any) -> None:
    """Merge attributes from duplicate `source` lead into `target` lead if missing."""
    for field in [
        "phone", "website", "rating", "review_count", "category",
        "address", "street", "city", "state", "postal_code", "country",
        "price_level", "latitude", "longitude", "primary_email",
        "linkedin", "facebook", "instagram", "twitter", "youtube", "tiktok",
        "contact_page_url", "place_id", "google_maps_url"
    ]:
        curr_val = getattr(target, field, None)
        src_val = getattr(source, field, None)
        if (curr_val is None or curr_val == "") and (src_val is not None and src_val != ""):
            setattr(target, field, src_val)

    # Merge emails list
    target_emails = getattr(target, "emails", []) or []
    source_emails = getattr(source, "emails", []) or []
    if source_emails:
        combined_emails = list(dict.fromkeys(target_emails + source_emails))
        setattr(target, "emails", combined_emails)


def deduplicate_leads(leads: List[Any]) -> List[Any]:
    """
    Deduplicate a list of leads using multi-signal identification and smart merging.
    Merges contact information across duplicate sightings so no data is lost.
    """
    unique_leads: List[Any] = []
    key_to_lead_index: Dict[str, int] = {}

    for lead in leads:
        lead_keys = get_lead_dedup_keys(lead)
        existing_idx = None
        
        # Check if any key matches an existing unique lead
        for k in lead_keys:
            if k in key_to_lead_index:
                existing_idx = key_to_lead_index[k]
                break

        if existing_idx is not None:
            # Duplicate found -> Merge missing fields into existing lead
            existing_lead = unique_leads[existing_idx]
            merge_lead_attributes(existing_lead, lead)
            for k in lead_keys:
                key_to_lead_index[k] = existing_idx
        else:
            # New unique lead
            new_idx = len(unique_leads)
            unique_leads.append(lead)
            for k in lead_keys:
                key_to_lead_index[k] = new_idx

    return unique_leads


def filter_leads(
    leads: List[Any],
    require_contact: bool = True,
    website_filter: str = "all",  # "all", "no_website", "has_website"
    require_phone_and_email: bool = False,
    require_phone: bool = False,
    require_email: bool = False,
    require_social: bool = False,
    min_reviews: Optional[int] = None,
    max_reviews: Optional[int] = None,
    exclude_junk: bool = False,
    min_ai_score: Optional[int] = None,
) -> List[Any]:
    """
    Filter leads based on website presence, contactability criteria, review counts, and AI intelligence.

    Args:
        leads:                   List of BusinessLead instances.
        require_contact:         If True, only keep leads that have at least 1 contact
                                 (phone or email) OR at least 1 social media profile.
        website_filter:          'all' (keep all), 'no_website' (only businesses without a website),
                                 or 'has_website' (only businesses with a website).
        require_phone_and_email: If True, keep only leads with BOTH phone and email.
        require_phone:           If True, must have phone.
        require_email:           If True, must have email.
        require_social:          If True, must have at least one social media link.
        min_reviews:             If set, lead must have at least this number of reviews.
        max_reviews:             If set, lead must have at most this number of reviews.
        exclude_junk:            If True, drop leads flagged as AI junk.
        min_ai_score:            If set, lead must have an AI score >= min_ai_score.

    Returns:
        Filtered list of BusinessLead instances.
    """
    filtered = []
    for lead in leads:
        # 0. AI Junk filter
        if exclude_junk and getattr(lead, "ai_is_junk", False):
            continue

        # 0b. AI Score filter
        if min_ai_score is not None:
            lead_score = getattr(lead, "ai_lead_score", None)
            if lead_score is not None and lead_score < min_ai_score:
                continue

        # 1. Website filter
        if website_filter == "no_website" and getattr(lead, "has_website", False):
            continue
        elif website_filter == "has_website" and not getattr(lead, "has_website", False):
            continue

        # 2. Strict combo requirement
        if require_phone_and_email and not getattr(lead, "has_phone_and_email", False):
            continue

        # 3. Individual channel requirements
        if require_phone and not getattr(lead, "has_phone", False):
            continue
        if require_email and not getattr(lead, "has_email", False):
            continue
        if require_social and not getattr(lead, "has_social", False):
            continue

        # 4. Minimum contactability: at least 1 contact info (phone or email) OR 1 social profile
        if require_contact and not getattr(lead, "is_contactable", False):
            continue

        # 5. Review count thresholds
        lead_revs = getattr(lead, "review_count", None)
        if min_reviews is not None and (lead_revs is None or lead_revs < min_reviews):
            continue
        if max_reviews is not None and lead_revs is not None and lead_revs > max_reviews:
            continue

        filtered.append(lead)

    return filtered
