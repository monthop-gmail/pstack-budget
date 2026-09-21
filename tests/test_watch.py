import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PSTACK = pathlib.Path("/tmp/pstack-src")
sys.path.insert(0, str(ROOT))
if PSTACK.is_dir():
    sys.path.insert(0, str(PSTACK))

from budget_addons.budget import watch_services as watch


class Result:
    def __init__(self, records):
        self.records = records

    def scalars(self):
        return self.records


class FakeSession:
    def __init__(self):
        self.source = None
        self.events = []

    async def get(self, _model, _id):
        return self.source

    async def execute(self, _query):
        return Result([self.source] if self.source else [])

    async def scalar(self, _query):
        return None

    def add(self, record):
        if isinstance(record, watch.WatchSource):
            self.source = record
        else:
            self.events.append(record)


def test_rss_items_supports_live_egp_encoding():
    xml = '<?xml version="1.0" encoding="Windows-874"?><rss><channel><item><guid>one</guid><title>ประกาศใหม่</title><link>https://example.test/1</link></item></channel></rss>'
    assert watch.rss_items(xml.encode("cp874"))[0]["title"] == "ประกาศใหม่"


@pytest.mark.asyncio
async def test_run_once_creates_an_announcement_event():
    page = b"<html><app-root></app-root></html>"
    feed = """<rss><channel><item><guid>notice-1</guid><title>ประกาศ</title><link>https://example.test/notice-1</link></item></channel></rss>""".encode()

    def fetcher(url):
        return watch.FetchResult(200, feed if "RssFeed" in url else page)

    session = FakeSession()
    assert (await watch.run_once(session, fetcher=fetcher))["events"] == 1
    assert session.events[0].event_key == "rss:notice-1"
