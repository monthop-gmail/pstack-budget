import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PSTACK = pathlib.Path("/tmp/pstack-src")
sys.path.insert(0, str(ROOT))
if PSTACK.is_dir():
    sys.path.insert(0, str(PSTACK))

from budget_addons.budget import watch_services as watch
from budget_addons.budget import egp_process3 as egp3


class Result:
    def __init__(self, records):
        self.records = records

    def scalars(self):
        return self.records


class FakeSession:
    def __init__(self):
        self.sources = {}
        self.events = []

    async def get(self, _model, _id):
        return self.sources.get(_id)

    async def execute(self, _query):
        return Result(list(self.sources.values()))

    async def scalar(self, _query):
        params = _query.compile().params
        source_id = params.get("source_id_1")
        key = params.get("event_key_1")
        return next((index for index, event in enumerate(self.events, 1)
                     if event.source_id == source_id and event.event_key == key), None)

    def add(self, record):
        if isinstance(record, watch.WatchSource):
            self.sources[record.id] = record
        else:
            self.events.append(record)


def row(project: str, title: str, date: str = "25/09/2569") -> str:
    return (f'<tr id="trDetail{project}"><td>1</td><td>หน่วยงาน</td>'
            f'<td><a onclick="chklink(\'{project}\',\'x\')">{title}</a></td>'
            f'<td>{date}</td></tr>')


def batch(*rows: str) -> bytes:
    return ("<table>" + "".join(rows) + "</table>").encode("cp874")


def test_process3_parser_keeps_distinct_notices_in_same_project():
    items = egp3.parse_items(batch(row("P1", "ประกาศแรก"), row("P1", "ประกาศที่สอง")))
    assert len(items) == 2
    assert items[0].key != items[1].key
    assert items[0].title == "ประกาศแรก"
    assert items[0].url == egp3.URL


def test_process3_crawl_paginates_and_removes_overlap():
    first = batch(*(row(f"P{i}", f"ประกาศ {i}") for i in range(50)))
    second = batch(row("P49", "ประกาศ 49"), row("P50", "ประกาศ 50"))
    calls = []

    def requester(method, params):
        calls.append((method, params))
        return first if method == "GET" else second

    result = egp3.crawl(requester, delay_seconds=0)
    assert (result.pages, result.complete, len(result.items)) == (2, True, 51)
    assert calls[1][1]["beginrec"] == "51"
    assert calls[1][1]["endrec"] == "101"


def test_process3_crawl_reports_page_cap_and_bad_html():
    full = batch(*(row(f"P{i}", f"ประกาศ {i}") for i in range(50)))
    result = egp3.crawl(lambda *_: full, max_pages=1, delay_seconds=0)
    assert (result.complete, result.pages) == (False, 1)
    assert "pagination cap" in result.warning
    stalled = egp3.crawl(lambda *_: full, max_pages=3, delay_seconds=0)
    assert not stalled.complete
    assert "did not advance" in stalled.warning
    with pytest.raises(ValueError, match="no announcement rows"):
        egp3.crawl(lambda *_: b"<html>changed</html>", delay_seconds=0)


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
    item = egp3.parse_items(batch(row("P1", "ประกาศจาก Process3")))[0]
    crawler = lambda **_: egp3.CrawlResult([item], 1, True)
    assert (await watch.run_once(session, fetcher=fetcher, process3_crawler=crawler))["events"] == 2
    assert {event.event_key for event in session.events} == {"rss:notice-1", item.key}
    session.sources[watch.PROCESS3_SOURCE_ID].last_checked_at = None
    assert (await watch.run_once(session, fetcher=fetcher, process3_crawler=crawler))["events"] == 0


@pytest.mark.asyncio
async def test_run_once_records_incomplete_crawl_warning():
    session = FakeSession()
    fetcher = lambda _: watch.FetchResult(200, b"<html></html>")
    item = egp3.parse_items(batch(row("P1", "ประกาศ")))[0]
    crawler = lambda **_: egp3.CrawlResult([item], 1, False, "Process3 pagination cap reached")
    totals = await watch.run_once(session, fetcher=fetcher, process3_crawler=crawler)
    assert totals["errors"] == 1
    assert "pagination cap" in session.sources[watch.PROCESS3_SOURCE_ID].last_error
    assert session.events[0].event_key == item.key
