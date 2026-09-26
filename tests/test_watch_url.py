import base64
import pathlib
import sys

import pytest
from fastapi import HTTPException
from starlette.requests import Request

ROOT = pathlib.Path(__file__).resolve().parents[1]
PSTACK = pathlib.Path("/tmp/pstack-src")
sys.path.insert(0, str(ROOT))
if PSTACK.is_dir():
    sys.path.insert(0, str(PSTACK))

from budget_addons.budget import watch_url
from budget_addons.budget.routes import WatchSourceInput, watch_create_source


@pytest.mark.parametrize("url", [
    "http://localhost/test", "http://127.0.0.1/", "http://169.254.169.254/latest/",
    "http://10.0.0.1/", "http://example.org:8080/", "file:///etc/passwd",
    "https://user:pass@example.org/", "https://example.org/?token=secret",
    "https://example.org/#fragment", "http://singlelabel/",
    "https://[64:ff9b::8.8.8.8]/", "https://[::8.8.8.8]/",
])
def test_rejects_nonpublic_or_credential_urls(url):
    with pytest.raises(ValueError):
        watch_url.validate_public_url(url)


def test_public_fetch_rejects_private_dns_answer():
    resolver = lambda *_args, **_kwargs: [(0, 0, 0, "", ("127.0.0.1", 443))]
    with pytest.raises(ValueError, match="private"):
        watch_url.fetch_public("https://example.org/news", resolver=resolver)


def test_public_fetch_rejects_mixed_public_private_dns_answers():
    resolver = lambda *_args, **_kwargs: [
        (0, 0, 0, "", ("93.184.215.14", 443)),
        (0, 0, 0, "", ("10.0.0.5", 443)),
    ]
    with pytest.raises(ValueError, match="private"):
        watch_url.fetch_public("https://example.org/news", resolver=resolver)


@pytest.mark.parametrize("answer", ["64:ff9b::a00:1", "::8.8.8.8"])
def test_public_fetch_rejects_ipv6_translation_dns_answers(answer):
    resolver = lambda *_args, **_kwargs: [(0, 0, 0, "", (answer, 443))]
    with pytest.raises(ValueError, match="private"):
        watch_url.fetch_public("https://example.org/news", resolver=resolver)


def test_public_fetch_pins_verified_address_and_rejects_redirect(monkeypatch):
    calls = []

    class Response:
        status = 302

        def getheader(self, _name, default=""):
            return default

        def read(self, _size):
            return b""

    class Connection:
        def __init__(self, host, port, address):
            calls.append((host, port, address))

        def request(self, *_args, **_kwargs):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(watch_url, "_PinnedHTTPSConnection", Connection)
    resolver = lambda *_args, **_kwargs: [(0, 0, 0, "", ("93.184.215.14", 443))]
    with pytest.raises(ValueError, match="redirects"):
        watch_url.fetch_public("https://example.org/news", resolver=resolver)
    assert calls == [("example.org", 443, "93.184.215.14")]


@pytest.mark.asyncio
async def test_authenticated_user_can_register_url(monkeypatch):
    monkeypatch.setenv("BUDGET_PASSWORD", "test-password")
    monkeypatch.setenv("BUDGET_API_USER", "team")
    encoded = base64.b64encode(b"team:test-password")
    request = Request({"type": "http", "headers": [(b"authorization", b"Basic " + encoded)]})

    class Session:
        source = None

        async def get(self, _model, _id):
            return self.source

        def add(self, source):
            self.source = source

        async def commit(self):
            pass

    session = Session()
    data = WatchSourceInput(name=" News ", url="https://example.org/news")
    created = await watch_create_source(request, data, session)
    assert created["id"].startswith("user-")
    assert created["name"] == "News"
    with pytest.raises(HTTPException) as exc:
        await watch_create_source(request, data, session)
    assert exc.value.status_code == 409
    other = await watch_create_source(request, WatchSourceInput(url="https://another.example.org/"), Session())
    assert other["name"] == "another.example.org"
