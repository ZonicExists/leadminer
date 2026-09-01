"""
Data schemas for Google Maps Leads and Scraper Configurations.
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class BusinessLead(BaseModel):
    """Data model representing a business lead extracted from Google Maps & enriched from its website."""
    # Google Maps Core Data
    name: str = ""
    category: str = ""
    subcategories: List[str] = Field(default_factory=list)
    rating: Optional[float] = None
    review_count: Optional[int] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    street: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    website: Optional[str] = None
    google_maps_url: Optional[str] = None
    place_id: Optional[str] = None
    price_level: Optional[str] = None
    status: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    is_claimed: Optional[bool] = None
    search_query: str = ""

    # Website Enrichment Data
    emails: List[str] = Field(default_factory=list)
    primary_email: Optional[str] = None
    linkedin: Optional[str] = None
    facebook: Optional[str] = None
    instagram: Optional[str] = None
    twitter: Optional[str] = None
    youtube: Optional[str] = None
    tiktok: Optional[str] = None
    contact_page_url: Optional[str] = None
    enrichment_status: str = "pending"  # "enriched", "failed", "no_website", "skipped"

    @property
    def has_website(self) -> bool:
        """True if the business has a valid website URL."""
        return bool(self.website and self.website.strip())

    @property
    def has_phone(self) -> bool:
        """True if the business has a phone number."""
        return bool(self.phone and self.phone.strip())

    @property
    def has_email(self) -> bool:
        """True if the business has at least one valid email address."""
        return bool((self.primary_email and self.primary_email.strip()) or (self.emails and len(self.emails) > 0))

    @property
    def has_social(self) -> bool:
        """True if the business has at least one linked social profile."""
        return bool(self.facebook or self.instagram or self.linkedin or self.twitter or self.youtube or self.tiktok)

    @property
    def has_phone_and_email(self) -> bool:
        """True if the business has BOTH phone and email linked."""
        return self.has_phone and self.has_email

    @property
    def is_contactable(self) -> bool:
        """
        True if the lead has at least 1 contact method (phone or email)
        OR at least 1 social media profile.
        """
        return self.has_phone or self.has_email or self.has_social

    @property
    def contact_channels(self) -> str:
        """Summary list of all available outreach channels (e.g. 'Phone, Email, Instagram')."""
        channels = []
        if self.has_phone:
            channels.append("Phone")
        if self.has_email:
            channels.append("Email")
        if self.facebook:
            channels.append("Facebook")
        if self.instagram:
            channels.append("Instagram")
        if self.linkedin:
            channels.append("LinkedIn")
        if self.twitter:
            channels.append("Twitter/X")
        if self.youtube:
            channels.append("YouTube")
        if self.tiktok:
            channels.append("TikTok")
        return ", ".join(channels) if channels else "None"

    def to_flat_dict(self) -> Dict[str, Any]:
        """Convert lead into a flat dictionary suitable for CSV / Excel export."""
        return {
            "Business Name": self.name,
            "Category": self.category,
            "Has Website": "Yes" if self.has_website else "No",
            "Website": self.website or "",
            "Phone": self.phone or "",
            "Email": self.primary_email or (", ".join(self.emails) if self.emails else ""),
            "Contact Channels": self.contact_channels,
            "Has Phone & Email": "Yes" if self.has_phone_and_email else "No",
            "Rating": self.rating if self.rating is not None else "",
            "Review Count": self.review_count if self.review_count is not None else "",
            "LinkedIn": self.linkedin or "",
            "Instagram": self.instagram or "",
            "Facebook": self.facebook or "",
            "Twitter/X": self.twitter or "",
            "YouTube": self.youtube or "",
            "TikTok": self.tiktok or "",
            "All Emails": ", ".join(self.emails) if self.emails else "",
            "Contact Page": self.contact_page_url or "",
            "Address": self.address or "",
            "City": self.city or "",
            "State": self.state or "",
            "Postal Code": self.postal_code or "",
            "Country": self.country or "",
            "Status": self.status or "",
            "Price Level": self.price_level or "",
            "Is Claimed": "Yes" if self.is_claimed is True else ("No" if self.is_claimed is False else ""),
            "Latitude": self.latitude if self.latitude is not None else "",
            "Longitude": self.longitude if self.longitude is not None else "",
            "Google Maps URL": self.google_maps_url or "",
            "Search Query": self.search_query or "",
            "Enrichment Status": self.enrichment_status,
        }


class ScrapeConfig(BaseModel):
    """Configuration options for a scraping job."""
    queries: List[str]
    limit_per_query: int = 20  # 0 for unlimited / until end of list
    enrich_contacts: bool = True  # Crawl websites for emails & social links
    headless: bool = True
    delay: float = 1.0  # Pause between interactions
    enrich_concurrency: int = 10
    enrich_timeout_sec: int = 12
    proxy: Optional[str] = None
    proxy_file: Optional[str] = None
    enable_captcha_solver: bool = False
    solver_ext: str = "captchasonic"
    solver_path: Optional[str] = None
    output_path: Optional[str] = None
    export_format: str = "csv"  # "csv", "xlsx", "json", "all"
