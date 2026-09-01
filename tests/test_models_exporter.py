"""
Tests for Data Models and File Exporters (CSV, XLSX, JSON).
"""
import os
import json
import pandas as pd
from src.models import BusinessLead
from src.exporter import export_leads


def test_business_lead_flat_dict():
    lead = BusinessLead(
        name="Tech Innovators LLC",
        category="Software Company",
        rating=4.9,
        review_count=85,
        phone="+1 512-555-1234",
        address="100 Congress Ave, Austin, TX 78701",
        city="Austin",
        state="TX",
        postal_code="78701",
        country="USA",
        website="https://techinnovators.io",
        emails=["contact@techinnovators.io", "jobs@techinnovators.io"],
        primary_email="contact@techinnovators.io",
        linkedin="https://linkedin.com/company/techinnovators",
        is_claimed=True,
    )

    flat = lead.to_flat_dict()
    assert flat["Business Name"] == "Tech Innovators LLC"
    assert flat["Category"] == "Software Company"
    assert flat["Rating"] == 4.9
    assert flat["Review Count"] == 85
    assert flat["Phone"] == "+1 512-555-1234"
    assert flat["Email"] == "contact@techinnovators.io"
    assert "jobs@techinnovators.io" in flat["All Emails"]
    assert flat["LinkedIn"] == "https://linkedin.com/company/techinnovators"
    assert flat["Is Claimed"] == "Yes"


def test_export_csv_and_json(tmp_path):
    lead1 = BusinessLead(
        name="Austin Dental Care",
        category="Dentist",
        rating=4.8,
        review_count=120,
        phone="512-555-7890",
        website="https://austindental.example",
        primary_email="hello@austindental.example",
    )
    lead2 = BusinessLead(
        name="Capital City Law",
        category="Law Firm",
        rating=5.0,
        review_count=30,
        phone="512-555-4321",
        website="https://capitallaw.example",
        primary_email="info@capitallaw.example",
    )
    leads = [lead1, lead2]

    # Test CSV Export
    csv_file = str(tmp_path / "test_leads.csv")
    res_csv = export_leads(leads, csv_file, export_format="csv")
    assert os.path.exists(res_csv)

    df = pd.read_csv(res_csv)
    assert len(df) == 2
    assert "Business Name" in df.columns
    assert "Email" in df.columns
    assert df.iloc[0]["Business Name"] == "Austin Dental Care"

    # Test JSON Export
    json_file = str(tmp_path / "test_leads.json")
    res_json = export_leads(leads, json_file, export_format="json")
    assert os.path.exists(res_json)

    with open(res_json, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert len(data) == 2
        assert data[0]["name"] == "Austin Dental Care"

    # Test XLSX Export
    xlsx_file = str(tmp_path / "test_leads.xlsx")
    res_xlsx = export_leads(leads, xlsx_file, export_format="xlsx")
    assert os.path.exists(res_xlsx)


def test_lead_contactability_properties():
    from src.models import BusinessLead

    # Lead with no website, but has phone and Facebook (Prime Web Builder prospect)
    lead_no_web = BusinessLead(
        name="Bob's Plumbing",
        phone="512-555-1111",
        facebook="https://facebook.com/bobsplumbing",
    )
    assert not lead_no_web.has_website
    assert lead_no_web.has_phone
    assert not lead_no_web.has_email
    assert lead_no_web.has_social
    assert lead_no_web.is_contactable
    assert not lead_no_web.has_phone_and_email
    assert "Phone" in lead_no_web.contact_channels
    assert "Facebook" in lead_no_web.contact_channels

    flat = lead_no_web.to_flat_dict()
    assert flat["Has Website"] == "No"
    assert flat["Phone"] == "512-555-1111"
    assert "Facebook" in flat["Contact Channels"]

    # Lead with both phone and email
    lead_both = BusinessLead(
        name="Alice Dental",
        phone="512-555-2222",
        primary_email="alice@dental.com",
        website="https://alicedental.com",
    )
    assert lead_both.has_website
    assert lead_both.has_phone_and_email
    assert lead_both.is_contactable

    # Empty / uncontactable lead (no phone, email, or social)
    lead_empty = BusinessLead(name="Ghost Business")
    assert not lead_empty.has_phone
    assert not lead_empty.has_email
    assert not lead_empty.has_social
    assert not lead_empty.is_contactable


def test_filter_leads():
    from src.models import BusinessLead
    from src.utils import filter_leads

    l1_no_web = BusinessLead(name="No Web Plumber", phone="512-555-0001")
    l2_has_web = BusinessLead(name="Has Web Dentist", website="https://dentist.com", phone="512-555-0002")
    l3_both = BusinessLead(name="Complete Law Firm", website="https://law.com", phone="512-555-0003", primary_email="info@law.com")
    l4_ghost = BusinessLead(name="Uncontactable LLC")  # no phone, email, or social

    all_leads = [l1_no_web, l2_has_web, l3_both, l4_ghost]

    # 1. Require at least 1 contact or social (drops l4_ghost)
    contactable = filter_leads(all_leads, require_contact=True)
    assert len(contactable) == 3
    assert l4_ghost not in contactable

    # 2. No Website Only (web builder prospects)
    no_web_only = filter_leads(all_leads, require_contact=True, website_filter="no_website")
    assert len(no_web_only) == 1
    assert no_web_only[0].name == "No Web Plumber"

    # 3. Has Website Only
    has_web_only = filter_leads(all_leads, require_contact=True, website_filter="has_website")
    assert len(has_web_only) == 2
    assert {l.name for l in has_web_only} == {"Has Web Dentist", "Complete Law Firm"}

    # 4. Require both phone and email
    both_only = filter_leads(all_leads, require_phone_and_email=True)
    assert len(both_only) == 1
    assert both_only[0].name == "Complete Law Firm"

    # 5. Min review count filter
    l1_no_web.review_count = 5
    l2_has_web.review_count = 45
    l3_both.review_count = 180

    min_40_revs = filter_leads(all_leads, min_reviews=40)
    assert len(min_40_revs) == 2
    assert {l.name for l in min_40_revs} == {"Has Web Dentist", "Complete Law Firm"}
