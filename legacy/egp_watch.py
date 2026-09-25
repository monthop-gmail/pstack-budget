# Public mirror of the deployed Process3+RSS watcher.
# Runtime paths and internal contact were replaced before publication.
#!/usr/bin/env python3
"""เฝ้าดูประกาศ e-GP แล้วจับคู่กับรายการครุภัณฑ์รถในงบ 2570

ดึง RSS ทางการและผลค้นหาสาธารณะ Process3 แบบแบ่งชุด เพื่อไม่พึ่ง RSS ที่แสดง
ประกาศเพียงส่วนน้อย เก็บประกาศลง SQLite และทำเครื่องหมายรายการที่ตรง watchlist

  python3 egp_watch.py            เก็บประกาศรอบปกติ
  python3 egp_watch.py --report   พิมพ์สรุปรายการที่ตรง 7 วันล่าสุด
"""
import hashlib, html, os, re, sqlite3, sys, time, urllib.request
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

RSS = "https://process.gprocurement.go.th/EPROCRssFeedWeb/egpannouncerss.xml"
PROCESS3 = "https://process3.gprocurement.go.th/egp2procmainWeb/procsearch.sch"
PROCESS3_SEARCH = {"homeflag": "A", "proc_id": "FPRO9965", "servlet": "FPRO9965Servlet",
                   "methodId": "", "announceType": "2"}
PROCESS3_SEARCH_URL = PROCESS3 + "?" + urlencode(PROCESS3_SEARCH)
MAX_GROUPS = 20
PAGE_SIZE = 50
DB = os.environ.get("EGP_WATCH_DB", "./data/egp_watch.db")
BUDGET_DB = os.environ.get("BUDGET_DB", "./data/budget2570.db")
UA = "budget2570-watch/1.0"
TH = timezone(timedelta(hours=7))

# คำที่บ่งว่าเป็นการจัดซื้อรถตามหมวดที่เราติดตาม (ตรงกับ vehicle_extract.py)
KEYWORDS = ["รถบรรทุกน้ำ", "รถน้ำ", "รถดับเพลิง", "รถกู้ภัย", "รถบรรทุกขยะ", "รถขยะ", "เก็บขนมูลฝอย",
            "รถดูดสิ่งปฏิกูล", "ดูดโคลน", "รถพยาบาล", "แทรกเตอร์", "รถไถ", "รถขุด", "แบคโฮ",
            "รถตัก", "รถเกรด", "รถบด", "รถกระเช้า", "รถเครน", "รถบรรทุก", "รถสุขา", "รถผลิตน้ำ"]


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("cp874", "replace")


def parse(xml: str):
    out = []
    for block in re.findall(r"<item>(.*?)</item>", xml, re.S):
        get = lambda tag: (re.search(rf"<{tag}>(.*?)</{tag}>", block, re.S) or [None, ""])[1]
        title = html.unescape(re.sub(r"<.*?>", " ", get("title"))).strip()
        out.append({"title": re.sub(r"\s+", " ", title),
                    "link": html.unescape(get("link")).strip(),
                    "pub": html.unescape(get("pubDate")).strip(),
                    "desc": re.sub(r"\s+", " ", html.unescape(re.sub(r"<.*?>", " ", get("description")))).strip()})
    m = re.search(r"<countbyday>(\d+)</countbyday>", xml)
    return out, int(m.group(1)) if m else -1


def parse_process3(response):
    """Parse a server batch; the response is Windows-874 despite its headers."""
    response.encoding = "cp874"
    soup = BeautifulSoup(response.text, "html.parser")
    items = []
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
            title_match = re.search(r"chklink\('[^']*','[^']*','[^']*','[^']*','(.*?)','\d{4}'", onclick, re.S)
            title = html.unescape(title_match.group(1)).replace("&nbsp;", " ").strip() if title_match else ""
        if not title:
            continue
        published = texts[3]
        identity = "\x1f".join((project_id, title, published, onclick))
        items.append({"id": "p3:" + hashlib.sha256(identity.encode()).hexdigest(),
                      "title": title, "link": PROCESS3_SEARCH_URL, "pub": published,
                      "desc": " | ".join(texts[1:])})
    return items


def process3_page_params(group):
    return {"govStatus": "A", "announceType": "2", "budgetYear": "", "deptId": "",
            "deptSubId": "", "moiId": "", "methodId": "", "typeId": "",
            "project_id": "", "projectName": "", "announceSDate": "", "announceEDate": "",
            "projectMoneyS": "", "projectMoneyE": "", "projectStatus": "", "priceBuild": "",
            "beginrec": str(PAGE_SIZE * (group - 1) + 1),
            "endrec": str(PAGE_SIZE * group + 1), "grouppage": str(group),
            "homeflag": "A", "servlet": "FPRO9965Servlet", "proc_id": "FPRO9965",
            "mode": "SEARCH"}


def fetch_process3(max_groups=MAX_GROUPS, delay_seconds=1):
    """Fetch bounded search batches with one cookie session; return completeness."""
    if not 1 <= max_groups <= 100 or delay_seconds < 0:
        raise ValueError("invalid Process3 limits")
    seen = set()
    items = []
    complete = False
    warning = ""
    with requests.Session() as session:
        session.headers.update({"User-Agent": UA, "Accept": "text/html"})
        for group in range(1, max_groups + 1):
            if group > 1 and delay_seconds:
                time.sleep(delay_seconds)
            response = (session.get(PROCESS3, params=PROCESS3_SEARCH, timeout=30) if group == 1
                        else session.post(PROCESS3, data=process3_page_params(group), timeout=30))
            response.raise_for_status()
            if len(response.content) > 2_000_000:
                raise ValueError("Process3 response exceeds size limit")
            batch = parse_process3(response)
            if group == 1 and not batch:
                raise ValueError("Process3 returned no announcement rows; page format may have changed")
            new = [item for item in batch if item["id"] not in seen]
            if not new:
                warning = f"Process3 pagination did not advance at group {group}"
                break
            items.extend(new)
            seen.update(item["id"] for item in new)
            if len(batch) < PAGE_SIZE:
                complete = True
                break
    if not complete and not warning:
        warning = f"Process3 pagination cap reached after {max_groups} groups"
    return items, complete, warning


def db():
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS ann(
      id TEXT PRIMARY KEY, title TEXT, link TEXT, pub TEXT, descr TEXT,
      first_seen TEXT, matched INTEGER DEFAULT 0, keyword TEXT, notified INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS runs(ts TEXT, items INTEGER, new INTEGER, matched INTEGER, countbyday INTEGER);
    CREATE INDEX IF NOT EXISTS i_ann_seen ON ann(first_seen);
    CREATE INDEX IF NOT EXISTS i_ann_match ON ann(matched, first_seen);
    """)
    return con


def match(text: str):
    t = text.replace(" ", "")
    for k in KEYWORDS:
        if k.replace(" ", "") in t:
            return k
    return ""


def collect():
    errors = []
    rss_items, process3_items, countbyday = [], [], -1
    try:
        rss_items, countbyday = parse(fetch(RSS))
    except (OSError, ValueError) as exc:
        errors.append(f"RSS: {type(exc).__name__}")
    try:
        process3_items, complete, warning = fetch_process3()
        if not complete:
            errors.append(warning)
    except (requests.RequestException, OSError, ValueError) as exc:
        errors.append(f"Process3: {type(exc).__name__}")
    if not rss_items and not process3_items:
        raise RuntimeError("both e-GP sources returned no usable announcements: " + "; ".join(errors))
    con = db()
    now = datetime.now(TH).isoformat(timespec="seconds")
    new = hit = 0
    for it in rss_items + process3_items:
        key = it.get("id") or hashlib.sha1((it["link"] or it["title"]).encode()).hexdigest()[:16]
        if con.execute("SELECT 1 FROM ann WHERE id=?", (key,)).fetchone():
            continue
        kw = match(it["title"] + " " + it["desc"])
        con.execute("INSERT INTO ann(id,title,link,pub,descr,first_seen,matched,keyword)"
                    " VALUES(?,?,?,?,?,?,?,?)",
                    (key, it["title"], it["link"], it["pub"], it["desc"], now, 1 if kw else 0, kw))
        new += 1
        hit += 1 if kw else 0
    con.execute("INSERT INTO runs VALUES(?,?,?,?,?)", (now, len(rss_items) + len(process3_items), new, hit, countbyday))
    con.commit()
    print(f"{now} | RSS={len(rss_items)} Process3={len(process3_items)} countbyday={countbyday} | new={new} matched={hit}")
    if errors:
        print("warning:", "; ".join(errors))
    con.close()
    return new, hit


def report(days=7):
    con = db()
    since = (datetime.now(TH) - timedelta(days=days)).isoformat(timespec="seconds")
    rows = con.execute("SELECT title,link,pub,keyword,first_seen FROM ann"
                       " WHERE matched=1 AND first_seen>=? ORDER BY first_seen DESC", (since,)).fetchall()
    print(f"ประกาศที่ตรงกับรายการรถ {days} วันล่าสุด: {len(rows)} รายการ")
    for t, l, p, k, s in rows:
        print(f"  [{k}] {t[:100]}\n      {p} · {l}")
    tot = con.execute("SELECT COUNT(*), SUM(matched) FROM ann").fetchone()
    last = con.execute("SELECT ts,items,new,matched,countbyday FROM runs ORDER BY ts DESC LIMIT 5").fetchall()
    print(f"\nสะสมทั้งหมด {tot[0]:,} ประกาศ · ตรงกับรายการรถ {tot[1] or 0:,}")
    print("รอบล่าสุด:", *[f"\n  {r[0]} items={r[1]} new={r[2]} matched={r[3]} countbyday={r[4]}" for r in last])
    con.close()


if __name__ == "__main__":
    if "--report" in sys.argv:
        report()
    else:
        for attempt in range(3):
            try:
                collect()
                break
            except Exception as e:                      # e-GP ล่มบ่อยช่วงกลางคืน
                print("error:", e, "(retry in 60s)" if attempt < 2 else "(give up)")
                if isinstance(e, sqlite3.OperationalError) and "readonly" in str(e).lower():
                    sys.exit(1)
                if attempt < 2:
                    time.sleep(60)
                else:
                    sys.exit(1)
