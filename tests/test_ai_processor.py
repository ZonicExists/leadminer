"""
Unit tests for Ollama AI Lead Intelligence and Junk Processor.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.models import BusinessLead
from src.ai_processor import OllamaClient
from src.utils import filter_leads


def test_lead_prompt_construction():
    client = OllamaClient()
    lead = BusinessLead(
        name="Best Plumber 24/7 Fast",
        category="Plumbing service",
        rating=4.9,
        review_count=120,
        phone="555-123-4567",
        website=None,
    )
    prompt = client._build_lead_prompt(lead)
    assert "Best Plumber 24/7 Fast" in prompt
    assert "None (No Website)" in prompt
    assert "555-123-4567" in prompt
    assert "120 reviews" in prompt


def test_heuristic_fallback_scoring():
    client = OllamaClient()
    
    # High-value lead: no website, high reviews, has phone
    hot_lead = BusinessLead(name="City Cafe", review_count=55, phone="1234567890", website=None)
    client._apply_heuristic_scoring(hot_lead)
    assert hot_lead.ai_lead_score >= 8
    assert "website" in hot_lead.ai_pitch_angle.lower()

    # Lower-value lead: has website, 0 reviews, no phone
    low_lead = BusinessLead(name="Old Biz", review_count=0, website="http://example.com")
    client._apply_heuristic_scoring(low_lead)
    assert low_lead.ai_lead_score <= 5


@pytest.mark.anyio
async def test_analyze_lead_with_mocked_ollama():
    client = OllamaClient(model="qwen2.5vl:7b")
    lead = BusinessLead(
        name="BEST GAMING CAFE 24/7 TOP",
        category="Video game arcade",
        rating=4.8,
        review_count=45,
        phone="099740 16999",
        website=None,
    )

    mock_json = {
        "is_junk": False,
        "junk_reason": None,
        "cleaned_name": "Katroz Gaming Cafe",
        "cleaned_category": "Gaming Lounge",
        "lead_score": 9,
        "pitch_angle": "Active gaming hub with 45 reviews and direct phone line, perfect candidate for a booking portal.",
        "summary": "Local esports gaming arcade and cafe."
    }

    with patch.object(client, "_query_model_json", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = mock_json
        async with AsyncMock() as mock_session:
            enriched = await client.analyze_lead(lead, mock_session)
            assert enriched.ai_is_junk is False
            assert enriched.ai_cleaned_name == "Katroz Gaming Cafe"
            assert enriched.ai_cleaned_category == "Gaming Lounge"
            assert enriched.ai_lead_score == 9
            assert "esports" in enriched.ai_summary.lower()


@pytest.mark.anyio
async def test_junk_lead_filtering():
    client = OllamaClient()
    l1 = BusinessLead(name="Real Business", phone="1234567890")
    l2 = BusinessLead(name="Test Listing 123", phone="0000000000")

    async def mock_analyze(lead, session):
        if "Test" in lead.name:
            lead.ai_is_junk = True
            lead.ai_junk_reason = "Test spam listing"
            lead.ai_lead_score = 1
        else:
            lead.ai_is_junk = False
            lead.ai_lead_score = 8
        return lead

    with patch.object(client, "analyze_lead", side_effect=mock_analyze):
        results = await client.process_leads_batch([l1, l2], filter_junk=True)
        assert len(results) == 1
        assert results[0].name == "Real Business"


def test_filter_leads_by_ai_score_and_junk():
    l1 = BusinessLead(name="High Lead", ai_lead_score=9, ai_is_junk=False, phone="1234567890")
    l2 = BusinessLead(name="Low Lead", ai_lead_score=4, ai_is_junk=False, phone="1234567890")
    l3 = BusinessLead(name="Junk Lead", ai_lead_score=1, ai_is_junk=True, phone="1234567890")

    all_leads = [l1, l2, l3]

    # Exclude junk
    no_junk = filter_leads(all_leads, exclude_junk=True)
    assert len(no_junk) == 2
    assert l3 not in no_junk

    # Min score >= 8
    high_value = filter_leads(all_leads, min_ai_score=8)
    assert len(high_value) == 1
    assert high_value[0].name == "High Lead"


def test_business_lead_flat_dict_with_ai():
    lead = BusinessLead(
        name="Original Name Inc",
        ai_cleaned_name="Clean Name",
        ai_lead_score=9,
        ai_pitch_angle="Pitch angle text",
        ai_is_junk=False,
        ai_summary="Great business",
        phone="555-0000",
    )
    flat = lead.to_flat_dict()
    assert flat["Business Name"] == "Clean Name"
    assert flat["Original Name"] == "Original Name Inc"
    assert flat["AI Lead Score"] == 9
    assert flat["AI Pitch Angle"] == "Pitch angle text"
    assert flat["Is Junk"] == "No"
    assert flat["AI Summary"] == "Great business"
