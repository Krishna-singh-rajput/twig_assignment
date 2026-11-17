"""Unit tests for scrapers, rate limiter, robots.txt, and politeness mechanisms."""

import time
import pytest
from unittest.mock import MagicMock, patch

from pipeline.scrapers.base import BaseScraper, DomainRateLimiter
from pipeline.scrapers.greenhouse import GreenhouseScraper
from pipeline.scrapers.lever import LeverScraper
from pipeline.scrapers.hackernews import HackerNewsScraper


def test_rate_limiter_throttles_rapid_requests():
    """Verify DomainRateLimiter enforces minimum delay between consecutive domain requests."""
    limiter = DomainRateLimiter(min_interval_seconds=0.2)
    domain = "api.example.com"

    start = time.time()
    limiter.wait(domain)
    limiter.wait(domain)
    limiter.wait(domain)
    elapsed = time.time() - start

    # 3 calls with 0.2s minimum interval should take >= 0.4s
    assert elapsed >= 0.38, f"Expected elapsed >= 0.38s, got {elapsed:.3f}s"


def test_robots_txt_allow_and_disallow():
    """Verify robots.txt rules are respected."""
    scraper = BaseScraper(user_agent="TestBot/1.0")

    mock_robots_txt = """
    User-agent: *
    Disallow: /admin/
    Disallow: /private/
    Allow: /public/
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = mock_robots_txt

    with patch.object(scraper.client, "get", return_value=mock_resp):
        assert scraper.can_fetch("https://example.com/public/jobs") is True
        assert scraper.can_fetch("https://example.com/admin/settings") is False
        assert scraper.can_fetch("https://example.com/private/data") is False

    scraper.close()


def test_greenhouse_html_stripping():
    """Verify HTML description is cleaned to readable structured text without tags."""
    raw_html = """
    <div>
        <h3>About the Role</h3>
        <p>Stripe is looking for a <strong>Senior Data Engineer</strong>.</p>
        <ul>
            <li>Build real-time pipelines with Spark &amp; Kafka</li>
            <li>Maintain data models in Snowflake</li>
        </ul>
        <br/>
        <p>Compensation: $180,000 - $240,000/yr.</p>
    </div>
    """
    cleaned = GreenhouseScraper._html_to_clean_text(raw_html)
    assert "<" not in cleaned
    assert ">" not in cleaned
    assert "Spark & Kafka" in cleaned
    assert "• Build real-time pipelines" in cleaned
    assert "$180,000 - $240,000/yr" in cleaned


def test_lever_content_type_validation():
    """Verify Lever scraper checks Content-Type header and rejects HTML responses gracefully."""
    scraper = LeverScraper(user_agent="TestBot/1.0")

    mock_html_resp = MagicMock()
    mock_html_resp.status_code = 200
    mock_html_resp.headers = {"content-type": "text/html; charset=utf-8"}
    mock_html_resp.text = "<html><body>Please solve captcha</body></html>"

    with patch.object(scraper, "fetch_url", return_value=mock_html_resp):
        postings = scraper.scrape_site("somecompany")
        # Should return empty without crashing
        assert postings == []

    scraper.close()


def test_hackernews_header_parsing_ordering():
    """Verify HN parser extracts company, title, and location regardless of pipe ordering."""
    # Order: Company | Role | Location
    c1, t1, l1 = HackerNewsScraper._parse_header_hints("Stripe | Senior Data Engineer | San Francisco, CA | Full-time")
    assert c1 == "Stripe"
    assert "Data Engineer" in t1
    assert "San Francisco" in l1

    # Order: Company | Location | Role
    c2, t2, l2 = HackerNewsScraper._parse_header_hints("Epsilon | Hybrid (Chicago, IL) | Senior Data Engineer | $150k")
    assert c2 == "Epsilon"
    assert "Data Engineer" in t2
    assert "Chicago" in l2


def test_polite_scraper_handles_404_gracefully():
    """Verify that a 404 response (e.g. Plaid on Lever) does not crash the scraper."""
    scraper = LeverScraper(user_agent="TestBot/1.0")

    mock_404_resp = MagicMock()
    mock_404_resp.status_code = 404
    mock_404_resp.headers = {"content-type": "application/json"}
    mock_404_resp.json.return_value = {"ok": False, "error": "Document not found"}

    with patch.object(scraper, "fetch_url", return_value=mock_404_resp):
        postings = scraper.scrape_site("plaid")
        assert postings == []

    scraper.close()
