"""
Unit tests for Scrape Session Checkpoint Persistence and Stop/Resume Controls.
"""
import os
import threading
import pytest
from src.models import BusinessLead
from src.config import SESSION_CHECKPOINT_FILE
from src.utils import (
    save_session_checkpoint,
    load_session_checkpoint,
    clear_session_checkpoint,
)
from src.scraper_pool import ScraperPool, WorkerResult


def test_session_checkpoint_save_and_load():
    """Test saving session checkpoint to disk and loading it back."""
    clear_session_checkpoint()
    try:
        lead1 = BusinessLead(
            name="Alpha Solar Systems",
            phone="1234567890",
            category="Solar Contractor",
            search_query="Solar in Austin, TX",
        )
        lead2 = BusinessLead(
            name="Beta Roofing & Gutters",
            phone="9876543210",
            category="Roofing contractor",
            search_query="Roofing in Austin, TX",
        )

        all_queries = ["Solar in Austin, TX", "Roofing in Austin, TX", "Plumbers in Austin, TX"]
        completed_queries = ["Solar in Austin, TX"]
        pending_queries = ["Roofing in Austin, TX", "Plumbers in Austin, TX"]

        save_session_checkpoint(
            status="running",
            queries=all_queries,
            completed_queries=completed_queries,
            pending_queries=pending_queries,
            leads=[lead1, lead2],
            config={"threads": 3, "limit": 15},
        )

        assert os.path.exists(SESSION_CHECKPOINT_FILE)

        data = load_session_checkpoint()
        assert data is not None
        assert data["status"] == "running"
        assert data["lead_count"] == 2
        assert len(data["leads"]) == 2
        assert data["completed_queries"] == ["Solar in Austin, TX"]
        assert len(data["pending_queries"]) == 2

        # Reconstruct BusinessLead instances
        reconstructed = [BusinessLead(**d) for d in data["leads"]]
        assert reconstructed[0].name == "Alpha Solar Systems"
        assert reconstructed[1].name == "Beta Roofing & Gutters"

    finally:
        clear_session_checkpoint()
        assert not os.path.exists(SESSION_CHECKPOINT_FILE)


def test_session_checkpoint_paused_state():
    """Test saving a paused session checkpoint."""
    clear_session_checkpoint()
    try:
        lead = BusinessLead(name="Delta Plumbing", phone="5551234567")
        save_session_checkpoint(
            status="paused",
            queries=["Query 1", "Query 2"],
            completed_queries=["Query 1"],
            pending_queries=["Query 2"],
            leads=[lead],
        )

        data = load_session_checkpoint()
        assert data is not None
        assert data["status"] == "paused"
        assert data["pending_queries"] == ["Query 2"]
        assert len(data["leads"]) == 1
    finally:
        clear_session_checkpoint()


@pytest.mark.anyio
async def test_scraper_pool_stop_event_cancellation():
    """Test that setting stop_event halts ScraperPool without crashing."""
    stop_event = threading.Event()
    stop_event.set()  # Pre-set stop event

    pool = ScraperPool(threads=2, stop_event=stop_event)
    queries = ["Test Query 1", "Test Query 2"]
    results = await pool.run(queries=queries, limit_per_query=5)

    assert len(results) == 2
    for r in results:
        assert r.error == "Stopped by user"
