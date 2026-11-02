"""Small, explicit client for the OpenAQ API v3."""

from __future__ import annotations

import json
import os
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE_URL = "https://api.openaq.org/v3"
USER_AGENT = "India-Air-Quality-Lab/0.1 (research and education)"


class OpenAQError(RuntimeError):
    """Raised when an OpenAQ request cannot be completed."""


class OpenAQClient:
    """Authenticated OpenAQ client with bounded retries and paged reads."""

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = 30,
        retries: int = 2,
        pause_seconds: float = 0.15,
    ) -> None:
        self.api_key = api_key or os.environ.get("OPENAQ_API_KEY")
        if not self.api_key:
            raise OpenAQError(
                "Set OPENAQ_API_KEY in your environment before calling the API. "
                "Never put the key in a command, source file, or Git commit."
            )
        self.timeout = timeout
        self.retries = retries
        self.pause_seconds = pause_seconds

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        query = f"?{urlencode(params)}" if params else ""
        request = Request(
            f"{BASE_URL}/{path.lstrip('/')}{query}",
            headers={
                "X-API-Key": self.api_key,
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
        )

        for attempt in range(self.retries + 1):
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                if exc.code == 429 or 500 <= exc.code < 600:
                    if attempt < self.retries:
                        time.sleep(min(2**attempt, 4))
                        continue
                if exc.code in (401, 403):
                    raise OpenAQError(
                        f"OpenAQ denied access (HTTP {exc.code}). "
                        "Check that the API key is active and that the endpoint is available to your account."
                    ) from None
                raise OpenAQError(f"OpenAQ returned HTTP {exc.code} for {path}.") from None
            except (TimeoutError, URLError) as exc:
                if attempt < self.retries:
                    time.sleep(min(2**attempt, 4))
                    continue
                reason = getattr(exc, "reason", exc)
                raise OpenAQError(f"Could not reach OpenAQ: {reason}") from None
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise OpenAQError("OpenAQ returned a response that was not valid JSON.") from None

        raise OpenAQError("OpenAQ request failed after retries.")

    def iter_locations(self, country_id: int = 9, page_size: int = 1000):
        """Yield India station metadata one page at a time."""
        page = 1
        while True:
            payload = self.get(
                "locations",
                {"countries_id": country_id, "limit": page_size, "page": page},
            )
            locations = payload.get("results", [])
            yield from locations
            found = payload.get("meta", {}).get("found")
            if not locations or (isinstance(found, int) and page * page_size >= found):
                break
            page += 1

    def sensor_daily(self, sensor_id: int, date_from: str, date_to: str):
        """Yield daily aggregates for one sensor in an inclusive date range."""
        page = 1
        while True:
            payload = self.get(
                f"sensors/{sensor_id}/days",
                {
                    "date_from": date_from,
                    "date_to": date_to,
                    "limit": 1000,
                    "page": page,
                },
            )
            rows = payload.get("results", [])
            yield from rows
            found = payload.get("meta", {}).get("found")
            if not rows or (isinstance(found, int) and page * 1000 >= found):
                break
            page += 1
            time.sleep(self.pause_seconds)
