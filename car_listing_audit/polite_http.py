from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Final
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests


DEFAULT_USER_AGENT: Final[str] = (
    "car-listing-audit-mvp/0.1 "
    "(public inventory audit; respects robots.txt; no login or bypass)"
)


@dataclass
class RobotsPolicy:
    parser: RobotFileParser
    user_agent: str

    @classmethod
    def load(cls, base_url: str, session: "PoliteSession") -> "RobotsPolicy":
        robots_url = urljoin(base_url, "/robots.txt")
        response = session.get_without_robots_check(robots_url)
        response.raise_for_status()
        parser = RobotFileParser(robots_url)
        parser.parse(response.text.splitlines())
        return cls(parser=parser, user_agent=session.user_agent)

    def ensure_allowed(self, url: str) -> None:
        if not self.parser.can_fetch(self.user_agent, url):
            raise PermissionError(f"robots.txt disallows fetching {url}")


class PoliteSession:
    """Small wrapper that centralizes user agent, timeouts, and request delay."""

    def __init__(self, user_agent: str = DEFAULT_USER_AGENT, delay_seconds: float = 2.0) -> None:
        self.user_agent = user_agent
        self.delay_seconds = delay_seconds
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": user_agent})
        self._last_request_at: float | None = None

    def _wait_if_needed(self) -> None:
        if self._last_request_at is None:
            return
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.delay_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def _get(self, url: str) -> requests.Response:
        self._wait_if_needed()
        response = self._session.get(url, timeout=30)
        self._last_request_at = time.monotonic()
        return response

    def get_without_robots_check(self, url: str) -> requests.Response:
        return self._get(url)

    def get(self, url: str, robots: RobotsPolicy) -> requests.Response:
        robots.ensure_allowed(url)
        return self._get(url)


def same_site_base(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}/"

