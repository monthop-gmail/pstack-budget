"""Public URL and feed watcher; persistence is supplied by pstack PostgreSQL."""

from __future__ import annotations

import asyncio
import hashlib
import html
import os
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import WatchEvent, WatchSource
from . import egp_process3
from .watch_url import fetch_public

DEFAULT_SOURCE_URL = "https://process5.gprocurement.go.th/egp-agpc01-web/announcement?keywordSearch=&advancedSearch=true"
DEFAULT_RSS_URL = "https://process.gprocurement.go.th/EPROCRssFeedWeb/egpannouncerss.xml"
PROCESS3_SOURCE_ID = "egp-process3-announcement"
USER_AGENT = "pstack-budget-watch/0.1 (+contact: operations)"
MAX_RESPONSE_BYTES = 2_000_000


@dataclass(frozen=True)
class FetchResult:
    status: int
    body: bytes
    etag: str = ""
    last_modified: str = ""


def fetch(url: str, opener: Callable[..., object] = urllib.request.urlopen) -> FetchResult:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/html;q=0.8"})
    try:
        with opener(request, timeout=30) as response:  # type: ignore[arg-type]
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise ValueError("response exceeds size limit")
            return FetchResult(response.status, body, response.headers.get("ETag", ""), response.headers.get("Last-Modified", ""))
    except urllib.error.HTTPError as exc:
        return FetchResult(exc.code, exc.read(MAX_RESPONSE_BYTES))


def _text(value: str | None) -> str:
    return " ".join(html.unescape(value or "").split())


def rss_items(body: bytes) -> list[dict[str, str]]:
    try:
        root = ET.fromstring(body)
    except LookupError:
        if b"windows-874" not in body[:200].lower() and b"tis-620" not in body[:200].lower():
            raise
        root = ET.fromstring(body.decode("cp874"))
    result: list[dict[str, str]] = []
    for item in list(root.findall(".//item")) + list(root.findall(".//{*}entry")):
        link_node = item.find("link")
        if link_node is None:
            link_node = item.find("{*}link")
        link = "" if link_node is None else link_node.get("href", "") or _text(link_node.text)
        title = _text(item.findtext("title") or item.findtext("{*}title"))
        guid = _text(item.findtext("guid") or item.findtext("id") or item.findtext("{*}id"))
        published = _text(item.findtext("pubDate") or item.findtext("published") or item.findtext("{*}published") or item.findtext("updated") or item.findtext("{*}updated"))
        summary = _text(item.findtext("description") or item.findtext("{*}summary") or item.findtext("{*}content"))
        key = guid or link or hashlib.sha256((title + published + summary).encode()).hexdigest()
        if title or link:
            result.append({"key": key, "title": title or "ประกาศ e-GP", "url": link, "published": published, "summary": summary})
    return result


async def seed_initial_source(session: AsyncSession) -> None:
    if await session.get(WatchSource, "egp-process5-announcement") is None:
        session.add(WatchSource(id="egp-process5-announcement", name="e-GP Process5 announcements", url=DEFAULT_SOURCE_URL, feed_url=DEFAULT_RSS_URL))
    if await session.get(WatchSource, PROCESS3_SOURCE_ID) is None:
        session.add(WatchSource(id=PROCESS3_SOURCE_ID, name="e-GP Process3 public search", url=egp_process3.URL))


def _positive_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, str(default))))
    except ValueError:
        return default


async def run_once(
    session: AsyncSession,
    opener: Callable[..., object] = urllib.request.urlopen,
    fetcher: Callable[[str], FetchResult] | None = None,
    process3_crawler: Callable[..., egp_process3.CrawlResult] | None = None,
) -> dict[str, int]:
    await seed_initial_source(session)
    sources = list((await session.execute(select(WatchSource).where(WatchSource.enabled.is_(True)))).scalars())
    totals = {"sources": 0, "events": 0, "errors": 0, "changes": 0}
    now = datetime.now(UTC)
    async def get_url(url: str, *, public: bool = False) -> FetchResult:
        # Injecting a deterministic fetcher keeps unit tests independent from
        # the platform's thread executor. Runtime uses a worker thread so a
        # 30-second public HTTP timeout never blocks the event loop.
        if fetcher is not None:
            return fetcher(url)
        if public:
            status, body, etag, last_modified = await asyncio.to_thread(fetch_public, url)
            return FetchResult(status, body, etag, last_modified)
        return await asyncio.to_thread(fetch, url, opener)

    for source in sources:
        if source.id == PROCESS3_SOURCE_ID:
            interval = _positive_int("WATCH_EGP3_INTERVAL_MINUTES", 60)
            if source.last_checked_at and (now - source.last_checked_at).total_seconds() < interval * 60:
                continue
            totals["sources"] += 1
            try:
                crawler = process3_crawler or egp_process3.crawl
                max_pages = min(_positive_int("WATCH_EGP3_MAX_PAGES", 20), 100)
                result = (crawler(max_pages=max_pages, delay_seconds=1.0) if process3_crawler
                          else await asyncio.to_thread(crawler, max_pages=max_pages, delay_seconds=1.0))
                digest = hashlib.sha256("\n".join(item.key for item in result.items).encode()).hexdigest()
                source.last_checked_at, source.last_status = now, 200
                source.content_hash = digest
                source.last_error = None if result.complete else (result.warning or "Process3 crawl incomplete")
                if not result.complete:
                    totals["errors"] += 1
                for item in result.items:
                    if await session.scalar(select(WatchEvent.id).where(WatchEvent.source_id == source.id, WatchEvent.event_key == item.key)) is None:
                        session.add(WatchEvent(source_id=source.id, event_key=item.key, kind="announcement", title=item.title, url=item.url, published_at=item.published, summary=item.summary, discovered_at=now))
                        totals["events"] += 1
            except ValueError as exc:
                totals["errors"] += 1
                source.last_checked_at, source.last_status, source.last_error = now, None, str(exc)[:500]
            continue
        totals["sources"] += 1
        try:
            is_user_source = source.id != "egp-process5-announcement"
            page = await get_url(source.url, public=is_user_source)
            if not 200 <= page.status < 300:
                raise ValueError(f"source returned HTTP {page.status}")
            digest = hashlib.sha256(page.body).hexdigest()
            changed = bool(source.content_hash and source.content_hash != digest)
            source.last_checked_at, source.last_status, source.last_error = now, page.status, None
            source.content_hash, source.etag, source.last_modified = digest, page.etag, page.last_modified
            if changed:
                key = "page:" + digest
                if await session.scalar(select(WatchEvent.id).where(WatchEvent.source_id == source.id, WatchEvent.event_key == key)) is None:
                    session.add(WatchEvent(source_id=source.id, event_key=key, kind="source_changed", title=f"หน้า {source.name} มีการเปลี่ยนแปลง", url=source.url, discovered_at=now))
                    totals["changes"] += 1
            if source.feed_url:
                feed = await get_url(source.feed_url, public=is_user_source)
                if not 200 <= feed.status < 300:
                    raise ValueError(f"RSS returned HTTP {feed.status}")
                for item in rss_items(feed.body):
                    key = "rss:" + item["key"]
                    if await session.scalar(select(WatchEvent.id).where(WatchEvent.source_id == source.id, WatchEvent.event_key == key)) is None:
                        session.add(WatchEvent(source_id=source.id, event_key=key, kind="announcement", title=item["title"], url=item["url"], published_at=item["published"], summary=item["summary"], discovered_at=now))
                        totals["events"] += 1
        except (OSError, ValueError, ET.ParseError) as exc:
            totals["errors"] += 1
            source.last_checked_at, source.last_error = now, str(exc)[:500]
    return totals
