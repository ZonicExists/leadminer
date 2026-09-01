import os
from typing import List

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIT_SOLVER_DIR = os.path.join(BASE_DIR, "Bit Solver")
EXTENSIONS_DIR = os.path.join(BIT_SOLVER_DIR, "extensions")
CAPTCHASONIC_EXT_PATH = os.path.join(EXTENSIONS_DIR, "captchasonic")
NOPECHA_EXT_PATH = os.path.join(EXTENSIONS_DIR, "nopecha")
PROXY_CONFIG_FILE = os.path.join(BASE_DIR, ".proxy_config.json")

DEFAULT_USER_AGENTS: List[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:133.0) Gecko/20100101 Firefox/133.0",
]

DEFAULT_TIMEOUT_MS: int = 30000
DEFAULT_SCROLL_PAUSE: float = 1.5
DEFAULT_ENRICH_CONCURRENCY: int = 10
DEFAULT_ENRICH_TIMEOUT_SEC: int = 12

# Common subpages to check for emails and social links
CONTACT_SUBPAGES = [
    "/contact",
    "/contact-us",
    "/about",
    "/about-us",
    "/contactus",
    "/aboutus",
    "/our-team",
    "/team",
    "/reach-us",
    "/get-in-touch",
]

# Social media domains to extract
SOCIAL_DOMAINS = {
    "linkedin": ["linkedin.com/company", "linkedin.com/in"],
    "facebook": ["facebook.com", "fb.com"],
    "instagram": ["instagram.com"],
    "twitter": ["twitter.com", "x.com"],
    "youtube": ["youtube.com", "youtu.be"],
    "tiktok": ["tiktok.com"],
    "pinterest": ["pinterest.com"],
}

# Image / file / placeholder patterns to filter out of email regex matches
JUNK_EMAIL_PATTERNS = [
    r"\.(png|jpg|jpeg|gif|webp|svg|css|js|woff|woff2|ttf|eot)$",
    r"^user@",
    r"^example@",
    r"^email@",
    r"^test@",
    r"^domain@",
    r"^info@yourdomain\.",
    r"^you@domain\.",
    r"^name@email\.",
    r"^sentry\.",
    r"wixpress\.com",
    r"sentry\.io",
    r"cloudflare\.com",
    r"wp-engine\.com",
]
