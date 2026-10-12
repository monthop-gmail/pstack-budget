"""Bounded public Process3 tender search; no document download or archive writes."""

from __future__ import annotations

import hashlib
import http.cookiejar
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from . import egp_process3

PROCESS5_REFERENCE = "https://process5.gprocurement.go.th/egp-agpc01-web/announcement?advancedSearch=true&keywordSearch="
PAGE_SIZE = egp_process3.PAGE_SIZE
MAX_PAGES = 6


def _thai_date(value: str) -> date | None:
    match = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})", value.strip())
    if not match:
        return None
    day, month, year = map(int, match.groups())
    try:
        return date(year - 543 if year > 2400 else year, month, day)
    except ValueError:
        return None


def _money(value: str) -> float:
    try:
        return float(re.sub(r"[^\d.]", "", value) or 0)
    except ValueError:
        return 0.0


def parse_tenders(body: bytes) -> list[dict]:
    """Extract tender fields from the public Windows-874 search table."""
    soup = BeautifulSoup(body.decode("cp874"), "html.parser")
    rows: list[dict] = []
    for tr in soup.select("tr[id^='trDetail']"):
        cells = tr.find_all("td", recursive=False)
        if len(cells) < 6:
            continue
        values = [" ".join(cell.get_text(" ", strip=True).split()) for cell in cells]
        dept, title, published, money, status = values[1:6]
        onclick = " ".join(tag.get("onclick", "") for tag in tr.find_all(onclick=True))
        if not title:
            title_match = re.search(r"chklink\('[^']*','[^']*','[^']*','[^']*','(.*?)','\d{4}'", onclick, re.S)
            title = BeautifulSoup(title_match.group(1), "html.parser").get_text(" ", strip=True) if title_match else ""
        if not title:
            continue
        project_match = re.search(r"เลขที่โครงการ\s*:\s*(\d{8,14})", title)
        project_id = project_match.group(1) if project_match else ""
        announced = _thai_date(published)
        identity = "\x1f".join((project_id, title, published))
        rows.append({
            "key": hashlib.sha256(identity.encode()).hexdigest(),
            "project_id": project_id,
            "dept": dept,
            "title": title,
            "announce_date": published,
            "announce_iso": announced.isoformat() if announced else "",
            "budget": _money(money),
            "status": status,
            "method": (re.search(r"ด้วยวิธี(\S+(?:\s*\([^)]*\))?)", title) or [None, ""])[1],
            # Process5 is a reference/search page, not an unverified deep link.
            "egp_link": PROCESS5_REFERENCE + urllib.parse.quote(project_id or title[:60]),
        })
    return rows


def _params(keyword: str, group: int) -> dict[str, str | bytes]:
    params: dict[str, str | bytes] = egp_process3.page_params(max(group, 2))
    params["beginrec"] = str(PAGE_SIZE * (group - 1) + 1)
    params["endrec"] = str(PAGE_SIZE * group + 1)
    params["grouppage"] = str(group)
    params["projectName"] = keyword.encode("cp874", "ignore")
    return params


def search_keyword(
    keyword: str,
    requester: Callable[[str, dict], bytes] | None = None,
    *,
    max_pages: int = MAX_PAGES,
    delay_seconds: float = 1.0,
) -> tuple[list[dict], bool, str]:
    if not keyword.strip() or not 1 <= max_pages <= MAX_PAGES or delay_seconds < 0:
        raise ValueError("invalid tender search limits")
    if requester is None:
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        requester = lambda method, params: egp_process3._request(method, params, opener)
    try:
        requester("GET", egp_process3.SEARCH)  # establish the public search session
        rows: list[dict] = []
        seen: set[str] = set()
        for group in range(1, max_pages + 1):
            if delay_seconds:
                time.sleep(delay_seconds)
            batch = parse_tenders(requester("POST", _params(keyword, group)))
            if group == 1 and not batch:
                return [], False, "Process3 returned no tender rows; no matches or page format changed"
            new = [row for row in batch if row["key"] not in seen]
            for row in new:
                seen.add(row["key"])
                row["keyword"] = keyword
            rows.extend(new)
            if len(batch) < PAGE_SIZE:
                return rows, True, ""
            if not new:
                return rows, False, "Process3 tender pagination did not advance"
        return rows, False, f"Process3 tender pagination cap reached after {max_pages} pages"
    except urllib.error.HTTPError as exc:
        raise ValueError(f"Process3 returned HTTP {exc.code}") from exc
    except (OSError, urllib.error.URLError) as exc:
        raise ValueError(f"Process3 request failed: {type(exc).__name__}") from exc


def find_tenders(
    keywords: list[str],
    *,
    days: int = 60,
    include_all: bool = False,
    today: date | None = None,
    searcher: Callable[[str], tuple[list[dict], bool, str]] = search_keyword,
) -> dict:
    if not keywords or len(keywords) > 8 or not 7 <= days <= 365:
        raise ValueError("invalid tender query")
    since = (today or datetime.now(ZoneInfo("Asia/Bangkok")).date()) - timedelta(days=days)
    discovered: list[dict] = []
    warnings: list[str] = []
    for keyword in keywords:
        batch, complete, warning = searcher(keyword)
        if not complete:
            warnings.append(f"{keyword}: {warning}")
        discovered.extend(batch)
    discovered.sort(key=lambda row: row["announce_iso"], reverse=True)
    rows: list[dict] = []
    seen: set[str] = set()
    for row in discovered:
        identity = row["project_id"] or row["key"]
        if identity in seen:
            continue
        seen.add(identity)
        if not include_all:
            if "ยกเลิก" in row["status"]:
                continue
            announced = _thai_date(row["announce_date"])
            if announced and announced < since:
                continue
        rows.append(row)
    return {"rows": rows, "count": len(rows), "complete": not warnings, "warnings": warnings}
