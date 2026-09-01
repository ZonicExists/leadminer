"""
Tests for utilities, email extraction, social links discovery, and URL cleansing.
"""
import os
import pytest
from src.utils import (
    clean_url,
    clean_phone,
    extract_coordinates,
    parse_address_components,
    extract_valid_emails,
    extract_social_links,
    deduplicate_leads,
    parse_proxy_string,
    to_proxy_url,
    ProxyManager,
)
from src.models import BusinessLead


def test_clean_url():
    # Google redirect URL
    redirect_url = "https://www.google.com/url?q=https%3A%2F%2Fexample.com%2Flanding&sa=D&sntz=1"
    assert clean_url(redirect_url) == "https://example.com/landing"

    # Tracking params stripping
    tracking_url = "https://mybusiness.com/?utm_source=google&utm_medium=cpc"
    assert clean_url(tracking_url) == "https://mybusiness.com"

    # Plain schema addition
    assert clean_url("mybusiness.com") == "https://mybusiness.com"


def test_clean_phone():
    assert clean_phone("(512) 555-0199") == "(512) 555-0199"
    assert clean_phone("+1 555-123-4567 ext 12") == "+1 555-123-4567 ext 12"
    assert clean_phone("invalid") is None
    assert clean_phone("") is None


def test_extract_coordinates():
    url1 = "https://www.google.com/maps/place/Austin,+TX/@30.267153,-97.7430608,12z/data=!3m1!4b1"
    lat1, lng1 = extract_coordinates(url1)
    assert lat1 == pytest.approx(30.267153)
    assert lng1 == pytest.approx(-97.7430608)

    url2 = "https://www.google.com/maps/place/data=!3m1!4b1!4m6!3m5!1s0x0:0x0!8m2!3d37.7749295!4d-122.4194155"
    lat2, lng2 = extract_coordinates(url2)
    assert lat2 == pytest.approx(37.7749295)
    assert lng2 == pytest.approx(-122.4194155)


def test_parse_address_components():
    addr = "701 Brazos St #100, Austin, TX 78701, USA"
    comp = parse_address_components(addr)
    assert comp["street"] == "701 Brazos St #100"
    assert comp["city"] == "Austin"
    assert "TX" in comp["state"]
    assert "78701" in comp["postal_code"]
    assert comp["country"] == "USA"


def test_extract_valid_emails():
    sample_html = """
    <div>
        <p>Contact us at info@apexroofing.com or sales@apexroofing.com</p>
        <img src="banner@2x.png" />
        <a href="mailto:support@apexroofing.com">Support</a>
        <span>Dummy example@example.com or user@domain.com</span>
        <span>Sentry trace: sentry.io@sentry.io</span>
    </div>
    """
    emails = extract_valid_emails(sample_html)
    assert "info@apexroofing.com" in emails
    assert "sales@apexroofing.com" in emails
    assert "support@apexroofing.com" in emails
    assert "banner@2x.png" not in emails
    assert "example@example.com" not in emails


def test_extract_social_links():
    sample_html = """
    <div>
        <a href="https://www.linkedin.com/company/apex-roofing-tx/">LinkedIn</a>
        <a href="https://instagram.com/apexroofing">Instagram</a>
        <a href="https://www.facebook.com/apexroofingtx">Facebook</a>
        <a href="https://twitter.com/apex_roofs">Twitter</a>
        <a href="https://www.facebook.com/sharer/sharer.php?u=foo">Share on Facebook</a>
    </div>
    """
    socials = extract_social_links(sample_html)
    assert socials["linkedin"] == "https://www.linkedin.com/company/apex-roofing-tx/"
    assert socials["instagram"] == "https://instagram.com/apexroofing"
    assert socials["facebook"] == "https://www.facebook.com/apexroofingtx"
    assert socials["twitter"] == "https://twitter.com/apex_roofs"


def test_deduplicate_leads():
    l1 = BusinessLead(name="Apex Roofing", phone="512-555-0100", google_maps_url="https://maps.google.com/place/1")
    l2 = BusinessLead(name="Apex Roofing Duplicate", phone="512-555-0100", google_maps_url="https://maps.google.com/place/1")
    l3 = BusinessLead(name="Texas Solar Solutions", phone="512-555-0200", google_maps_url="https://maps.google.com/place/2")

    deduped = deduplicate_leads([l1, l2, l3])
    assert len(deduped) == 2
    assert deduped[0].name == "Apex Roofing"
    assert deduped[1].name == "Texas Solar Solutions"


def test_parse_proxy_string():
    # URL format
    p1 = parse_proxy_string("http://alice:secret123@proxy.example.com:8080")
    assert p1["server"] == "http://proxy.example.com:8080"
    assert p1["username"] == "alice"
    assert p1["password"] == "secret123"

    # IP:Port:User:Pass format
    p2 = parse_proxy_string("1.2.3.4:8000:myuser:mypass")
    assert p2["server"] == "http://1.2.3.4:8000"
    assert p2["username"] == "myuser"
    assert p2["password"] == "mypass"

    # IP:Port format
    p3 = parse_proxy_string("1.2.3.4:8080")
    assert p3["server"] == "http://1.2.3.4:8080"
    assert "username" not in p3

    # User format: host:port:username:password with session tokens
    user_proxy = "rp.scrapegw.com:6060:mucasp14nztsykr-session-ltvb8c7els-lifetime-5:58f20jxw64ukviq"
    p4 = parse_proxy_string(user_proxy)
    assert p4["server"] == "http://rp.scrapegw.com:6060"
    assert p4["username"] == "mucasp14nztsykr-session-ltvb8c7els-lifetime-5"
    assert p4["password"] == "58f20jxw64ukviq"

    # to_proxy_url conversion
    url = to_proxy_url(user_proxy)
    assert url == "http://mucasp14nztsykr-session-ltvb8c7els-lifetime-5:58f20jxw64ukviq@rp.scrapegw.com:6060"


def test_proxy_manager():
    pm = ProxyManager(["http://p1.com:8080", "http://p2.com:8080"])
    assert len(pm) == 2
    first = pm.get_next_proxy()
    second = pm.get_next_proxy()
    third = pm.get_next_proxy()

    assert first["server"] == "http://p1.com:8080"
    assert second["server"] == "http://p2.com:8080"
    assert third["server"] == "http://p1.com:8080"  # Wrapped around round-robin


def test_bit_solver_extension_exists():
    from src.config import BIT_SOLVER_DIR, CAPTCHASONIC_EXT_PATH, NOPECHA_EXT_PATH
    assert os.path.isdir(BIT_SOLVER_DIR), "Bit Solver parent directory must exist"
    assert os.path.isdir(CAPTCHASONIC_EXT_PATH), "CaptchaSonic extension directory must exist"
    assert os.path.isdir(NOPECHA_EXT_PATH), "NopeCHA extension directory must exist"


def test_parse_review_count():
    from src.utils import parse_review_count
    assert parse_review_count("(142)") == 142
    assert parse_review_count("(1,240)") == 1240
    assert parse_review_count("142 reviews") == 142
    assert parse_review_count("1 review") == 1
    assert parse_review_count("3,450 Reviews") == 3450
    assert parse_review_count("2.5K reviews") == 2500
    assert parse_review_count("4.8 stars 95 reviews") == 95
    assert parse_review_count("95") == 95
    assert parse_review_count("No reviews") is None
    assert parse_review_count("") is None
    assert parse_review_count(None) is None
