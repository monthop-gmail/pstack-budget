# Public archive snapshot of the original pre-Process3 script.
# Runtime paths and internal contact were replaced before publication.
#!/usr/bin/env python3
"""เฝ้าดูประกาศ e-GP แล้วจับคู่กับรายการครุภัณฑ์รถในงบ 2570

ดึง RSS ทางการของกรมบัญชีกลาง (ประกาศของ "วันนี้" เท่านั้น) จึงต้องรันวันละหลายรอบ
เก็บทุกประกาศลง SQLite แล้วทำเครื่องหมายรายการที่ตรงกับ watchlist ของเรา

  python3 egp_watch.py            เก็บประกาศรอบปกติ
  python3 egp_watch.py --report   พิมพ์สรุปรายการที่ตรง 7 วันล่าสุด
"""
import hashlib, html, os, re, sqlite3, sys, time, urllib.request
from datetime import datetime, timedelta, timezone

RSS = "https://process.gprocurement.go.th/EPROCRssFeedWeb/egpannouncerss.xml"
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
    xml = fetch(RSS)
    items, countbyday = parse(xml)
    con = db()
    now = datetime.now(TH).isoformat(timespec="seconds")
    new = hit = 0
    for it in items:
        key = hashlib.sha1((it["link"] or it["title"]).encode()).hexdigest()[:16]
        if con.execute("SELECT 1 FROM ann WHERE id=?", (key,)).fetchone():
            continue
        kw = match(it["title"] + " " + it["desc"])
        con.execute("INSERT INTO ann(id,title,link,pub,descr,first_seen,matched,keyword)"
                    " VALUES(?,?,?,?,?,?,?,?)",
                    (key, it["title"], it["link"], it["pub"], it["desc"], now, 1 if kw else 0, kw))
        new += 1
        hit += 1 if kw else 0
    con.execute("INSERT INTO runs VALUES(?,?,?,?,?)", (now, len(items), new, hit, countbyday))
    con.commit()
    print(f"{now} | feed items={len(items)} countbyday={countbyday} | new={new} matched={hit}")
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
                if attempt < 2:
                    time.sleep(60)
