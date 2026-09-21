"""Authenticated read-only access to the FY 2570 budget SQLite index.

The browser sign-in is deliberately password-only.  Automation can use HTTP Basic
with BUDGET_API_USER (normally ``team``) and the same password.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response, StreamingResponse

router = APIRouter(tags=["budget"])

MAX_ROWS = 500
COOKIE = "budget2570_session"
SESSION_DAYS = 60
SORTS = {
    "amount": "amount DESC",
    "amount_asc": "amount ASC",
    "book": "book_label, page, id",
    "qty": "qty DESC",
}
MODES = ("exact", "skel", "loose")


def _setting(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _password() -> str:
    value = _setting("BUDGET_PASSWORD")
    if not value or value.startswith("replace-with-"):
        raise HTTPException(503, "budget password is not configured")
    return value


def _secret() -> str:
    value = _setting("BUDGET_SESSION_SECRET") or _setting("PSTACK_SECRET_KEY")
    if not value or value.startswith("replace-with-"):
        raise HTTPException(503, "budget session secret is not configured")
    return value


def _db_path() -> Path:
    path = Path(_setting("BUDGET_DB_PATH", "/app/data/budget2570.db"))
    if not path.is_file():
        raise HTTPException(503, "budget index is not available")
    return path


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{_db_path()}?mode=ro", uri=True, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def _make_token(days: int = SESSION_DAYS) -> str:
    expiry = str(int(time.time()) + days * 86400)
    signature = hmac.new(_secret().encode(), expiry.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{expiry}.{signature}"


def _token_ok(token: str) -> bool:
    try:
        expiry, signature = token.split(".", 1)
        expected = hmac.new(_secret().encode(), expiry.encode(), hashlib.sha256).hexdigest()[:32]
        return secrets.compare_digest(signature, expected) and int(expiry) > time.time()
    except (ValueError, TypeError, HTTPException):
        return False


def _password_ok(password: str) -> bool:
    try:
        return secrets.compare_digest(password, _password())
    except HTTPException:
        return False


def _basic_ok(request: Request) -> bool:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("basic "):
        return False
    try:
        username, _, password = base64.b64decode(header[6:]).decode("utf-8").partition(":")
        return secrets.compare_digest(username, _setting("BUDGET_API_USER", "team")) and _password_ok(password)
    except (UnicodeDecodeError, ValueError):
        return False


def _authenticated(request: Request) -> bool:
    return _token_ok(request.cookies.get(COOKIE, "")) or _basic_ok(request)


def _login_redirect(request: Request) -> RedirectResponse:
    return RedirectResponse("/login?" + urlencode({"next": request.url.path}), status_code=303)


def _set_session(response: Response) -> Response:
    response.set_cookie(
        COOKIE, _make_token(), max_age=SESSION_DAYS * 86400,
        httponly=True, samesite="lax", secure=True, path="/",
    )
    return response


def _consonants(value: str) -> str:
    return re.sub(r"[^ก-ฮ0-9a-zA-Z]|ข", "", value.replace("ำ", "า"))


def _consonants_q(value: str) -> str:
    return re.sub(r"[^ก-ฮ0-9a-zA-Z]", "", value.replace("ำ", "า"))


def _build_query(params: dict[str, str], mode: str = "exact") -> tuple[str, list[object]]:
    where: list[str] = []
    args: list[object] = []
    for term in filter(None, (params.get("q") or "").split()):
        if mode == "exact":
            where.append("tnorm LIKE ?")
            args.append("%" + re.sub(r"\s+", "", term.replace("ำ", "ำ")) + "%")
        elif mode == "loose":
            where.append("skel LIKE ?")
            args.append(f"%{_consonants(term) or term}%")
        else:
            where.append("skelq LIKE ?")
            args.append(f"%{_consonants_q(term) or term}%")
    for column, key in (("ministry", "ministry"), ("agency", "agency"), ("province", "province"),
                        ("book_label", "book"), ("unit", "unit")):
        value = (params.get(key) or "").strip()
        if value:
            where.append(f"{column} = ?")
            args.append(value)
    buyer = (params.get("buyer") or "").strip()
    if buyer:
        where.append("buyer LIKE ?")
        args.append(f"%{buyer}%")
    for key, operator in (("min", ">="), ("max", "<=")):
        value = (params.get(key) or "").replace(",", "").strip()
        if value:
            try:
                where.append(f"amount {operator} ?")
                args.append(int(float(value)))
            except ValueError:
                pass
    if params.get("nonzero") == "1":
        where.append("amount > 0")
    return (" WHERE " + " AND ".join(where) if where else ""), args


def _resolve(params: dict[str, str], con: sqlite3.Connection):
    forced = params.get("mode", "auto")
    order = [forced] if forced in MODES else list(MODES)
    for mode in order:
        where, args = _build_query(params, mode)
        total = con.execute(
            f"SELECT COUNT(*) n, COALESCE(SUM(amount),0) s, COALESCE(SUM(project_total),0) pt "
            f"FROM items{where}", args,
        ).fetchone()
        if total["n"] or mode == order[-1]:
            return mode, where, args, total
    raise AssertionError("search mode resolution failed")


LOGIN_PAGE = """<!doctype html><html lang=\"th\"><head><meta charset=\"utf-8\">
<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>เข้าสู่ระบบ · ค้นงบ 2570</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f2f4f3;font-family:system-ui,sans-serif;color:#161a19}.card{background:#fff;border:1px solid #d7dbd8;border-radius:14px;padding:26px 22px;width:min(420px,90%)}h1{font-size:1.35rem;margin:0 0 7px;color:#1f4e79}p{color:#5e665f}input,button{box-sizing:border-box;width:100%;font:inherit;padding:13px;border-radius:9px}input{border:1px solid #b8c0ba}button{margin-top:14px;border:0;background:#1f4e79;color:#fff;font-weight:700}.err{color:#a3261e}</style></head><body><form class=\"card\" method=\"post\" action=\"/login\"><h1>ค้นงบประมาณ 2570</h1><p>ใส่รหัสผ่านครั้งเดียว ระบบจะจำไว้ 60 วันในเครื่องนี้</p>__ERR__<input type=\"hidden\" name=\"next\" value=\"__NEXT__\"><label for=\"pw\">รหัสผ่าน</label><input id=\"pw\" name=\"password\" type=\"password\" autocomplete=\"current-password\" autofocus><button>เข้าสู่ระบบ</button></form></body></html>"""


@router.get("/")
async def home(request: Request):
    if not _authenticated(request):
        return _login_redirect(request)
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if _token_ok(request.cookies.get(COOKIE, "")):
        return RedirectResponse(request.query_params.get("next", "/"), status_code=303)
    next_path = request.query_params.get("next", "/")
    return HTMLResponse(LOGIN_PAGE.replace("__ERR__", "").replace("__NEXT__", next_path if next_path.startswith("/") else "/"))


@router.post("/login")
async def login_submit(password: str = Form(""), next: str = Form("/")):
    target = next if next.startswith("/") else "/"
    if _password_ok(password):
        return _set_session(RedirectResponse(target, status_code=303))
    return HTMLResponse(LOGIN_PAGE.replace("__ERR__", '<p class="err">รหัสผ่านไม่ถูกต้อง</p>').replace("__NEXT__", target), status_code=401)


@router.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE, path="/")
    return response


@router.get("/api/search")
async def search(request: Request):
    if not _authenticated(request):
        raise HTTPException(401, "unauthorized", headers={"WWW-Authenticate": "Basic"})
    params = dict(request.query_params)
    try:
        limit = min(max(int(params.get("limit", "100")), 1), MAX_ROWS)
        offset = max(int(params.get("offset", "0")), 0)
    except ValueError:
        limit, offset = 100, 0
    con = _db()
    try:
        mode, where, args, total = _resolve(params, con)
        order = SORTS.get(params.get("sort", "amount"), SORTS["amount"])
        rows = con.execute(
            f"SELECT id,book,book_label,page,item_no,ministry,agency,buyer,province,tambon,amphoe,text,"
            f"amount,project_total,qty,unit,file FROM items{where} ORDER BY {order} LIMIT ? OFFSET ?",
            args + [limit, offset],
        ).fetchall()
    finally:
        con.close()
    result = [dict(row) for row in rows]
    for row in result:
        row["pdf"] = "/files/" + str(Path(row.pop("file")).with_suffix(".pdf"))
    return {"count": total["n"], "sum": total["s"], "project_total": total["pt"], "mode": mode, "rows": result}


@router.get("/api/facets")
async def facets(request: Request):
    """Return filter options calculated from the current search, like the legacy API."""
    if not _authenticated(request):
        raise HTTPException(401, "unauthorized", headers={"WWW-Authenticate": "Basic"})
    params = dict(request.query_params)
    con = _db()
    try:
        mode = params.get("mode", "auto")
        if mode not in MODES:
            mode, *_ = _resolve(params, con)

        def top(column: str, limit: int) -> list[dict]:
            query_key = "book" if column == "book_label" else column
            query_params = {key: value for key, value in params.items() if key != query_key}
            where, args = _build_query(query_params, mode)
            rows = con.execute(
                f"SELECT {column} v, COUNT(*) n, COALESCE(SUM(amount),0) s FROM items{where} "
                f"GROUP BY {column} HAVING v <> '' ORDER BY s DESC LIMIT ?", args + [limit],
            ).fetchall()
            return [dict(row) for row in rows]

        return {"ministry": top("ministry", 60), "agency": top("agency", 800),
                "province": top("province", 90), "book": top("book_label", 60), "unit": top("unit", 40)}
    finally:
        con.close()


@router.get("/api/export.csv")
async def export_csv(request: Request):
    """Export up to 20,000 matching rows in the legacy UTF-8-with-BOM CSV format."""
    if not _authenticated(request):
        raise HTTPException(401, "unauthorized", headers={"WWW-Authenticate": "Basic"})
    params = dict(request.query_params)
    con = _db()
    try:
        _, where, args, _ = _resolve(params, con)
        order = SORTS.get(params.get("sort", "amount"), SORTS["amount"])
        rows = con.execute(
            f"SELECT province,amphoe,tambon,ministry,agency,buyer,text,qty,unit,amount,project_total,"
            f"book_label,page,item_no FROM items{where} ORDER BY {order} LIMIT 20000", args,
        ).fetchall()
    finally:
        con.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["จังหวัด", "อำเภอ/เขต", "ตำบล/แขวง", "กระทรวง/กลุ่ม", "กรม/หน่วยรับงบ", "หน่วยงานที่ซื้อ",
                     "รายการ", "จำนวน", "หน่วย", "งบ 2570 (บาท)", "วงเงินทั้งโครงการ", "เล่ม", "หน้า", "ข้อ"])
    writer.writerows(list(row) for row in rows)
    return StreamingResponse(
        io.BytesIO(("\ufeff" + output.getvalue()).encode("utf-8")), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="budget2570_search.csv"'},
    )


@router.get("/files/{document_path:path}")
async def file(document_path: str, request: Request):
    if not _authenticated(request):
        return _login_redirect(request)
    root = Path(_setting("BUDGET_DOCS_PATH", "/docs")).resolve()
    candidate = (root / document_path).resolve()
    if root not in candidate.parents or not candidate.is_file() or candidate.suffix.lower() != ".pdf":
        raise HTTPException(404, "document not found")
    return FileResponse(candidate, media_type="application/pdf", content_disposition_type="inline")
