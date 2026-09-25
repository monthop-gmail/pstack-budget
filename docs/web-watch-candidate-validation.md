# Web Watch candidate validation — 2026-09-25

ทดสอบ commit `8a72d0d` กับ pstack `v0.5.1` ใน candidate แยกที่ใช้ PostgreSQL,
Redis, app และ worker ของตัวเอง ผูก API เฉพาะ loopback, mount โฟลเดอร์ข้อมูล
ทดสอบแบบ read-only และไม่เปลี่ยน production routing หรือใช้ index/PDF จริง.
ปิดแหล่ง e-GP ที่ seed มาเฉพาะใน candidate เพื่อทดสอบ URL ที่ผู้ใช้เพิ่มเอง.

| ตรวจสอบ | ผล |
| --- | --- |
| app startup และ health | ผ่าน; โมดูล `users,budget` โหลดได้ |
| `POST /api/watch/sources` แบบยืนยันตัวตน | `201`, สร้าง source จาก URL สาธารณะ |
| worker รอบแรก | HTTP 200, เก็บ baseline, ยังไม่มี event |
| จำลองเนื้อหาเปลี่ยนโดยตั้ง hash เดิมให้ต่างใน candidate | worker สร้าง `source_changed` 1 event |
| restart worker แล้วรันอีกครั้ง | event คง 1 รายการ ไม่ซ้ำ |
| `GET /api/watch/events` แบบยืนยันตัวตน | อ่าน event ได้ |
| ส่ง URL loopback | `422`, ปฏิเสธก่อน worker fetch |
| `pytest -q` | 24 ผ่าน |

หลังทดสอบหยุดและลบเฉพาะ containers/network ของ candidate แล้ว; volume ฐานข้อมูล
ทดสอบยังเก็บไว้เพื่อให้ตรวจหลักฐานหรือรันซ้ำได้. การจำลอง hash ไม่ใช่การเปลี่ยน
หน้าเว็บจริง จึงยังควรทดสอบกับเว็บที่ทีมเป็นเจ้าของก่อน production cutover.

ขั้นถัดไป: ทดสอบ RSS adapter ใน candidate, เพิ่มการจัดการ source (ปิด/แก้ไข)
และ adapter ที่แยกรายการใหม่จาก HTML ของแต่ละระบบ. ยังไม่มีการ deploy หรือ
สลับเส้นทาง production ในรอบนี้.
