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

## Web Watch: e-GP (backend first)

ระบบติดตามหน้า Process5 ที่ทีมระบุไว้และ RSS สาธารณะของ e-GP ต่อไป พร้อม adapter
ค้นหาประกาศสาธารณะบน Process3 ที่พัฒนาจากแนวทางทดลองเดิม: อ่าน HTML ภาษาไทย
Windows-874, ขอผลค้นหาเป็น batch ต่อเนื่อง, ตัดรายการซ้ำระหว่างหน้า และสร้าง
event จากเอกลักษณ์ของประกาศ (ไม่ใช้ project ID เพียงอย่างเดียว). URL ของ event
Process3 ชี้ไปยังหน้าค้นหาต้นทาง เพราะยังไม่มี deep link ที่ยืนยันว่าเสถียร.
แหล่งข้อมูลและประวัติ event แยกจาก Process5/RSS และเก็บใน PostgreSQL ของ pstack;
SQLite งบและ PDF ยังคง read-only. หน้า Process5 เป็น Angular SPA และการค้นหาถูก
คุ้มครองด้วย Cloudflare Turnstile; watcher **ไม่** ข้ามการป้องกันนั้น

Process3 ตรวจทุก 60 นาที (`WATCH_EGP3_INTERVAL_MINUTES`) และจำกัดที่ 20 batch
(`WATCH_EGP3_MAX_PAGES`, สูงสุด 100) โดยเว้น 1 วินาทีระหว่างคำขอ หากชนเพดาน
ระบบจะเก็บรายการที่เห็นและบันทึก warning ใน `last_error` เพื่อไม่อ้างว่าครบ.
หากโครงสร้างหน้าเปลี่ยนจนไม่พบประกาศ จะบันทึก error ไม่สร้าง event ปลอม.

เพิ่ม URL สาธารณะที่มนุษย์ต้องการติดตามได้ผ่าน API (ยังไม่มีหน้า UI):

```bash
curl --request POST --user "$BUDGET_API_USER:$BUDGET_PASSWORD" \
  --header 'Content-Type: application/json' \
  --data '{"url":"https://example.org/news"}' \
  http://127.0.0.1:8000/api/watch/sources
```

ใส่ `name` และ `feed_url` เพิ่มได้ถ้าทราบ RSS ของเว็บนั้น. URL ทั่วไปจะสร้าง
baseline ในรอบแรก แล้วแจ้ง `source_changed` เมื่อเนื้อหาหน้าเปลี่ยน; หากกำหนด
`feed_url` จะสร้าง event จากรายการใน feed ด้วย. การแยก "ประกาศใหม่" จาก HTML
ของ Joomla/WordPress/Odoo ยังต้องมี adapter เฉพาะภายหลัง. ระบบรับเฉพาะ URL
HTTP(S) สาธารณะ, ไม่รับ credential ใน URL, ไม่ตาม redirect และตรวจ/ตรึง IP
สาธารณะก่อนเชื่อมต่อ เพื่อไม่ให้ URL ที่เพิ่มพา worker เข้าถึงเครือข่ายภายใน.

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
