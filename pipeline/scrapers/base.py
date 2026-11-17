"""Base scraper implementation with politeness, robots.txt, rate-limiting, and retry logic."""

from __future__ import annotations

import logging
import random
import time
from typing import Dict, List, Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

logger = logging.getLogger("pipeline.scraper")


class DomainRateLimiter:
    """Thread-safe rate limiter guaranteeing <= 1 request/sec per domain."""

    def __init__(self, min_interval_seconds: float = 1.0) -> None:
        self.min_interval = min_interval_seconds
        self._last_request_time: Dict[str, float] = {}

    def wait(self, domain: str) -> None:
        now = time.time()
        last = self._last_request_time.get(domain, 0.0)
        elapsed = now - last
        if elapsed < self.min_interval:
            sleep_duration = self.min_interval - elapsed
            logger.debug(f"Rate limiting {domain}: sleeping {sleep_duration:.2f}s")
            time.sleep(sleep_duration)
        self._last_request_time[domain] = time.time()


class BaseScraper:
    """Abstract base scraper with politeness, robots.txt checking, and resilient retries."""

    def __init__(
        self,
        user_agent: str,
        request_delay: float = 1.0,
        timeout: float = 15.0,
        max_retries: int = 3,
    ) -> None:
        self.user_agent = user_agent
        self.timeout = timeout
        self.max_retries = max_retries
        self.rate_limiter = DomainRateLimiter(min_interval_seconds=request_delay)
        self._robot_parsers: Dict[str, RobotFileParser] = {}
        self.client = httpx.Client(
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=self.timeout,
            follow_redirects=True,
        )

    def close(self) -> None:
        """Close the underlying HTTP client session."""
        self.client.close()

    def __enter__(self) -> BaseScraper:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def _get_robot_parser(self, base_url: str) -> Optional[RobotFileParser]:
        """Fetch and cache robots.txt for a given domain."""
        parsed = urlparse(base_url)
        domain = parsed.netloc
        if domain in self._robot_parsers:
            return self._robot_parsers[domain]

        robots_url = f"{parsed.scheme}://{domain}/robots.txt"
        rp = RobotFileParser()
        rp.set_url(robots_url)
        try:
            # Polite fetch of robots.txt
            self.rate_limiter.wait(domain)
            res = self.client.get(robots_url, timeout=5.0)
            if res.status_code == 200:
                rp.parse(res.text.splitlines())
                logger.debug(f"Successfully parsed robots.txt for {domain}")
            else:
                logger.debug(f"robots.txt for {domain} returned status {res.status_code}, defaulting to allowed")
                rp.allow_all = True
        except Exception as e:
            logger.debug(f"Could not fetch robots.txt for {domain}: {e}. Defaulting to allowed.")
            rp.allow_all = True

        self._robot_parsers[domain] = rp
        return rp

    def can_fetch(self, url: str) -> bool:
        """Check if URL is permitted according to robots.txt."""
        try:
            rp = self._get_robot_parser(url)
            if rp is None:
                return True
            return rp.can_fetch(self.user_agent, url)
        except Exception as e:
            logger.warning(f"Error checking robots.txt for {url}: {e}")
            return True

    def fetch_url(self, url: str) -> Optional[httpx.Response]:
        """Fetch URL with rate-limiting, robots.txt verification, and exponential backoff retry."""
        parsed = urlparse(url)
        domain = parsed.netloc

        if not self.can_fetch(url):
            logger.warning(f"Politeness check: URL {url} disallowed by robots.txt, skipping.")
            return None

        for attempt in range(1, self.max_retries + 1):
            try:
                self.rate_limiter.wait(domain)
                logger.debug(f"Fetching {url} (attempt {attempt}/{self.max_retries})")
                response = self.client.get(url)

                if response.status_code == 200:
                    return response
                elif response.status_code in (429, 500, 502, 503, 504):
                    # Rate limited or server error, backoff
                    wait_time = (2 ** attempt) + random.uniform(0.1, 0.5)
                    logger.warning(
                        f"HTTP {response.status_code} for {url}. Backing off {wait_time:.2f}s..."
                    )
                    time.sleep(wait_time)
                elif response.status_code == 404:
                    logger.info(f"HTTP 404 Not Found for {url}")
                    return response
                else:
                    logger.warning(f"Unexpected HTTP {response.status_code} for {url}")
                    return response
            except (httpx.RequestError, httpx.TimeoutException) as exc:
                # Try fallback to standard library urllib on Windows socket/DNS glitch
                try:
                    import urllib.request
                    req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
                    with urllib.request.urlopen(req, timeout=self.timeout) as u_res:
                        content = u_res.read()
                        # Construct a mock httpx.Response
                        return httpx.Response(
                            status_code=u_res.status,
                            content=content,
                            headers=dict(u_res.headers),
                            request=httpx.Request("GET", url),
                        )
                except Exception as fb_exc:
                    logger.debug(f"urllib fallback also failed for {url}: {fb_exc}")

                wait_time = (2 ** attempt) + random.uniform(0.1, 0.5)
                logger.warning(
                    f"Request error fetching {url} ({exc}). Retrying in {wait_time:.2f}s..."
                )
                time.sleep(wait_time)
            except Exception as exc:
                logger.error(f"Unrecoverable error fetching {url}: {exc}")
                return None

        logger.error(f"Failed to fetch {url} after {self.max_retries} attempts.")
        return None
