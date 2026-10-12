import base64
import pathlib
import sys
from datetime import date

import pytest
from fastapi import HTTPException
from starlette.requests import Request

ROOT = pathlib.Path(__file__).resolve().parents[1]
PSTACK = pathlib.Path("/tmp/pstack-src")
sys.path.insert(0, str(ROOT))
if PSTACK.is_dir():
    sys.path.insert(0, str(PSTACK))

from budget_addons.budget import tenders as tender_service
from budget_addons.budget import routes


def tender_row(project_id="12345678901", *, status="เปิด", published="11/10/2569", title=None):
    title = title or f"ซื้อรถขุด เลขที่โครงการ : {project_id} ด้วยวิธีประกวดราคา"
    return (f'<tr id="trDetail{project_id}"><td>1</td><td>หน่วยงานทดสอบ</td>'
            f'<td>{title}</td><td>{published}</td><td>1,250,000.00 บาท</td>'
            f'<td>{status}</td></tr>')


def page(*rows):
    return ("<table>" + "".join(rows) + "</table>").encode("cp874")


def test_parse_tenders_keeps_structured_fields_and_reference_link():
    row = tender_service.parse_tenders(page(tender_row()))[0]
    assert row["project_id"] == "12345678901"
    assert row["announce_iso"] == "2026-10-11"
    assert row["budget"] == 1250000
    assert row["method"] == "ประกวดราคา"
    assert row["egp_link"].startswith(tender_service.PROCESS5_REFERENCE)


def test_keyword_search_uses_session_then_bounded_pages():
    full = page(*(tender_row(str(10000000000 + n)) for n in range(50)))
    calls = []

    def requester(method, params):
        calls.append((method, params))
        return b"" if method == "GET" else full

    rows, complete, warning = tender_service.search_keyword("รถขุด", requester, max_pages=2, delay_seconds=0)
    assert len(rows) == 50
    assert not complete and "did not advance" in warning
    assert [method for method, _ in calls] == ["GET", "POST", "POST"]
    assert calls[1][1]["projectName"] == "รถขุด".encode("cp874")
    assert calls[2][1]["beginrec"] == "51"


def test_keyword_search_marks_empty_and_capped_results_uncertain():
    empty, complete, warning = tender_service.search_keyword(
        "not-found", lambda method, _: b"" if method == "GET" else page(), delay_seconds=0,
    )
    assert empty == [] and not complete and "no tender rows" in warning
    full = page(*(tender_row(str(10000000000 + n)) for n in range(50)))
    rows, complete, warning = tender_service.search_keyword(
        "รถขุด", lambda method, _: b"" if method == "GET" else full,
        max_pages=1, delay_seconds=0,
    )
    assert len(rows) == 50 and not complete and "cap reached" in warning


def test_find_filters_cancellation_age_and_duplicate_projects():
    rows = tender_service.parse_tenders(page(
        tender_row("12345678901"),
        tender_row("12345678902", status="ยกเลิก"),
        tender_row("12345678903", published="01/01/2569"),
    ))
    result = tender_service.find_tenders(
        ["รถขุด", "รถตัก"], today=date(2026, 10, 12),
        searcher=lambda _: ([dict(row) for row in rows], True, ""),
    )
    assert result["count"] == 1
    assert result["rows"][0]["project_id"] == "12345678901"
    all_result = tender_service.find_tenders(
        ["รถขุด"], include_all=True, today=date(2026, 10, 12),
        searcher=lambda _: (rows, True, ""),
    )
    assert all_result["count"] == 3


def test_latest_cancelled_notice_suppresses_older_active_project():
    rows = tender_service.parse_tenders(page(
        tender_row("12345678901", published="10/10/2569"),
        tender_row("12345678901", published="11/10/2569", status="ยกเลิก"),
    ))
    result = tender_service.find_tenders(
        ["รถขุด"], today=date(2026, 10, 12),
        searcher=lambda _: (rows, True, ""),
    )
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_tender_api_requires_auth_and_valid_query(monkeypatch):
    monkeypatch.setenv("BUDGET_PASSWORD", "test-password")
    unauthorized = Request({"type": "http", "headers": []})
    with pytest.raises(HTTPException) as exc:
        await routes.tenders(unauthorized, q="รถขุด")
    assert exc.value.status_code == 401

    encoded = base64.b64encode(b"team:test-password")
    authorized = Request({"type": "http", "headers": [(b"authorization", b"Basic " + encoded)]})
    with pytest.raises(HTTPException) as exc:
        await routes.tenders(authorized, q="")
    assert exc.value.status_code == 422

    monkeypatch.setattr(routes, "find_tenders", lambda keywords, **_: {"count": len(keywords), "rows": []})
    result = await routes.tenders(authorized, q="รถขุด, รถตัก")
    assert result["count"] == 2
