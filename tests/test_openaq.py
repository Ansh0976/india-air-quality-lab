import json
from unittest.mock import patch
from urllib.error import HTTPError

import pytest

from aqi_lab.openaq import OpenAQClient, OpenAQError


def test_client_requires_key(monkeypatch):
    monkeypatch.delenv("OPENAQ_API_KEY", raising=False)
    with pytest.raises(OpenAQError, match="Set OPENAQ_API_KEY"):
        OpenAQClient(api_key="")


def test_request_sends_api_key_in_header_and_paginates():
    client = OpenAQClient("test-secret", retries=0)
    responses = [
        {"meta": {"found": 2}, "results": [{"id": 1}]},
        {"meta": {"found": 2}, "results": [{"id": 2}]},
    ]

    class Response:
        def __init__(self, value):
            self.value = value

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self):
            return json.dumps(self.value).encode()

    def fake_urlopen(request, timeout):
        assert request.get_header("X-api-key") == "test-secret"
        assert timeout == 30
        return Response(responses.pop(0))

    with patch("aqi_lab.openaq.urlopen", fake_urlopen):
        assert [row["id"] for row in client.iter_locations(page_size=1)] == [1, 2]


def test_auth_error_does_not_expose_key():
    client = OpenAQClient("do-not-print-this", retries=0)
    error = HTTPError("https://api.openaq.org/v3/locations", 401, "Unauthorized", {}, None)
    with patch("aqi_lab.openaq.urlopen", side_effect=error):
        with pytest.raises(OpenAQError) as caught:
            client.get("locations")
    assert "do-not-print-this" not in str(caught.value)
    assert "HTTP 401" in str(caught.value)
