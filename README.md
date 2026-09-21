# pstack-budget

แอป pstack สำหรับค้นงบประมาณรายจ่ายประจำปี 2570 โดยเก็บ index SQLite และเอกสาร PDF
เป็นข้อมูล read-only ที่ mount ตอน deploy ไม่ commit ข้อมูลหรือรหัสผ่านลง repository

## โครงสร้าง

- `budget_addons/budget/` — โมดูล pstack ของแอป: หน้า password-only, Basic Auth สำหรับ API, search และ PDF ที่กัน path traversal
- `data/budget2570.db` — SQLite index ที่ต้องจัดหาเมื่อ deploy (ถูก ignore)
- `BUDGET_DOCS_HOST_PATH` — host path ของโฟลเดอร์ PDF; container อ่านเป็น `/docs` เท่านั้น

## ตั้งค่าและรัน

คัดลอก `.env.example` เป็น `.env` แล้วตั้งค่า secret แบบสุ่มและรหัสผ่านจริงใน `.env` เท่านั้น
สำหรับ server เดิม ให้ชี้ `BUDGET_DOCS_HOST_PATH` ไปที่ชุดเอกสารและวาง index ที่ `data/budget2570.db`:

```bash
docker compose up -d --build
curl http://127.0.0.1:8000/healthz
curl --user "$BUDGET_API_USER:$BUDGET_PASSWORD" 'http://127.0.0.1:8000/api/search?q=การศึกษา&limit=1'
```

หน้าเว็บใช้เฉพาะ `BUDGET_PASSWORD`; API/curl ใช้ Basic Auth username จาก
`BUDGET_API_USER`. `/healthz` เปิดสาธารณะเพื่อ health check.

## Web Watch: e-GP Process5 (backend first)

รุ่นแรกติดตามหน้า Process5 ที่ทีมระบุไว้ และใช้ RSS สาธารณะของ e-GP เพื่อพบ
ประกาศใหม่ ระบบเก็บ state และ event ใน PostgreSQL ของ pstack; SQLite งบและ PDF
ยัง mount แบบ read-only. หน้า Process5 เป็น Angular SPA และการค้นหาถูกคุ้มครองด้วย
Cloudflare Turnstile ดังนั้น watcher **ไม่** scrape ผลค้นหาหรือพยายามข้ามการ
ป้องกันนั้น

หลัง deploy, ตรวจผลผ่าน API ที่ต้องยืนยันตัวตน:

```bash
curl --user "$BUDGET_API_USER:$BUDGET_PASSWORD" http://127.0.0.1:8000/api/watch/sources
curl --user "$BUDGET_API_USER:$BUDGET_PASSWORD" http://127.0.0.1:8000/api/watch/events
curl --request POST --user "$BUDGET_API_USER:$BUDGET_PASSWORD" http://127.0.0.1:8000/api/watch/run
```

worker เดิมของ pstack ทำงานทุก 15 นาทีเป็นค่าเริ่มต้น (`WATCH_INTERVAL_MINUTES`).

## Cutover แบบปลอดภัย

1. รัน compose นี้คนละ port/project กับ `budget2570-search` เดิม
2. ยืนยัน health, browser login, API Basic Auth, query ตัวอย่าง และเปิด PDF
3. สลับ upstream ที่ reverse proxy หลัง smoke test ผ่านเท่านั้น
4. เก็บ container เดิมไว้; rollback คือสลับ upstream กลับ
