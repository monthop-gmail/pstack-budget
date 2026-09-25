"""Public e-GP Process3 search adapter (no login or challenge bypass)."""

from __future__ import annotations

import hashlib
import http.cookiejar
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable

from bs4 import BeautifulSoup

URL = "https://process3.gprocurement.go.th/egp2procmainWeb/procsearch.sch"
SEARCH = {
    "homeflag": "A", "proc_id": "FPRO9965", "servlet": "FPRO9965Servlet",
    "methodId": "", "announceType": "2",
}
PAGE_SIZE = 50
MAX_RESPONSE_BYTES = 2_000_000
USER_AGENT = "pstack-budget-watch/0.2 (+contact: operations)"


@dataclass(frozen=True)
class Announcement:
    key: str
    title: str
    published: str
    summary: str
    url: str = URL


@dataclass(frozen=True)
class CrawlResult:
    items: list[Announcement]
    pages: int
    complete: bool
    warning: str = ""


def parse_items(body: bytes) -> list[Announcement]:
    """Parse one server batch; e-GP serves Thai text as Windows-874."""
    soup = BeautifulSoup(body.decode("cp874"), "html.parser")
    items: list[Announcement] = []
    for row in soup.select("tr[id^='trDetail']"):
        cells = row.find_all("td", recursive=False)
        if len(cells) < 4:
            continue
        texts = [" ".join(cell.get_text(" ", strip=True).split()) for cell in cells]
        onclick = " ".join(tag.get("onclick", "") for tag in row.find_all(onclick=True))
        project_match = re.search(r"(?:chklink|showPopupFileType9)\('([^']+)'", onclick)
        project_id = project_match.group(1) if project_match else ""
        title = texts[2]
        if not title:
            title_match = re.search(r"chklink\('[^']*','[^']*','[^']*','[^']*','(.*?)','\d{4}'", onclick, re.DOTALL)
            title = BeautifulSoup(title_match.group(1), "html.parser").get_text(" ", strip=True) if title_match else ""
        if not title:
            continue
        published = texts[3]
        summary = " | ".join(texts[1:])
        # A project can have several announcements; the notice details, not
        # project ID alone, form the event identity. Do not use row/page number.
        identity = "\x1f".join((project_id, title, published, onclick))
        key = "egp3:" + hashlib.sha256(identity.encode()).hexdigest()
        items.append(Announcement(key, title, published, summary))
    return items


def page_params(group: int) -> dict[str, str]:
    if group < 2:
        raise ValueError("pagination starts at group 2")
    return {
        "govStatus": "A", "announceType": "2", "budgetYear": "", "deptId": "",
        "deptSubId": "", "moiId": "", "methodId": "", "typeId": "",
        "project_id": "", "projectName": "", "announceSDate": "", "announceEDate": "",
        "projectMoneyS": "", "projectMoneyE": "", "projectStatus": "", "priceBuild": "",
        "beginrec": str(PAGE_SIZE * (group - 1) + 1),
        "endrec": str(PAGE_SIZE * group + 1), "grouppage": str(group),
        "homeflag": "A", "servlet": "FPRO9965Servlet", "proc_id": "FPRO9965", "mode": "SEARCH",
    }


def _request(method: str, params: dict[str, str], opener: object) -> bytes:
    data = urllib.parse.urlencode(params).encode()
    url = URL + "?" + urllib.parse.urlencode(params) if method == "GET" else URL
    request = urllib.request.Request(
        url, data=None if method == "GET" else data,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html"}, method=method,
    )
    with opener.open(request, timeout=30) as response:  # type: ignore[attr-defined]
        if not 200 <= response.status < 300:
            raise ValueError(f"Process3 returned HTTP {response.status}")
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("Process3 response exceeds size limit")
    return body


def crawl(
    requester: Callable[[str, dict[str, str]], bytes] | None = None,
    *,
    max_pages: int = 20,
    delay_seconds: float = 1.0,
) -> CrawlResult:
    """Fetch bounded batches with one cookie session and stable-key dedupe."""
    if max_pages < 1 or delay_seconds < 0:
        raise ValueError("invalid Process3 crawl limits")
    if requester is None:
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        requester = lambda method, params: _request(method, params, opener)
    seen: set[str] = set()
    items: list[Announcement] = []
    pages = 0
    complete = False
    warning = ""
    try:
        for group in range(1, max_pages + 1):
            if group > 1 and delay_seconds:
                time.sleep(delay_seconds)
            batch = parse_items(requester("GET", SEARCH) if group == 1 else requester("POST", page_params(group)))
            pages += 1
            if group == 1 and not batch:
                raise ValueError("Process3 returned no announcement rows; page format may have changed")
            new = [item for item in batch if item.key not in seen]
            items.extend(new)
            seen.update(item.key for item in new)
            if not new:
                warning = f"Process3 pagination did not advance at page {group}; results may be incomplete"
                break
            if len(batch) < PAGE_SIZE:
                complete = True
                break
    except urllib.error.HTTPError as exc:
        raise ValueError(f"Process3 returned HTTP {exc.code}") from exc
    except (OSError, urllib.error.URLError) as exc:
        raise ValueError(f"Process3 request failed: {type(exc).__name__}") from exc
    if not complete and not warning:
        warning = f"Process3 pagination cap reached after {pages} pages; results may be incomplete"
    return CrawlResult(items, pages, complete, warning)
