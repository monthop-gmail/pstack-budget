# Legacy e-GP watcher: rollback and health check

สถานะ ณ 2026-09-26: เจ้าของงานอนุมัติให้ปรับ `egp_watch.py` เมื่อ 2026-09-25.
สคริปต์ที่รันบนระบบเดิมเป็น source of truth สำหรับการปฏิบัติงานรอบนี้ ส่วน
`legacy/egp_watch.py` ใน repo public เป็น **mirror ที่ปกปิด path และ contact ภายใน**
ไม่ใช่ไฟล์ deploy โดยตรง. ก่อนเปลี่ยนครั้งต่อไปให้สำรองไฟล์ที่รันจริง, ทดสอบ
candidate, ติดตั้ง แล้วอัปเดต mirror ใน commit เดียวกันเพื่อไม่ให้สองชุด drift.

## สำเนาและการถอยกลับ

- สำเนาสคริปต์เดิมแบบตรงตัวชื่อ `egp_watch.py.backup-20260925` อยู่ข้างไฟล์ที่รัน.
- สำเนา SQLite ก่อนเปลี่ยนชื่อ `egp_watch.db.backup-20260925` อยู่ข้างฐานข้อมูล.
- หากต้อง rollback โค้ด ให้หยุด/เลี่ยงช่วง scheduler, คัดลอกสคริปต์สำรองทับ
  `egp_watch.py` โดยรักษา owner/mode เดิม, ตรวจ syntax แล้วรัน smoke ด้วยบัญชี
  เดียวกับ scheduler. จากนั้นตรวจรอบตามเวลาอีกครั้ง.

  เมื่ออยู่ในโฟลเดอร์ของ watcher แล้ว คำสั่งถอยกลับเฉพาะโค้ดคือ:

  ```bash
  sudo cp -p ./egp_watch.py.backup-20260925 ./egp_watch.py
  python3 -c 'import ast; ast.parse(open("egp_watch.py", encoding="utf-8").read())'
  ```

- **อย่าคัดลอก SQLite สำรองทับโดยอัตโนมัติ**: schema ไม่เปลี่ยน และฐานข้อมูล
  ปัจจุบันมีรายการที่เพิ่มหลังวันสำรอง การ restore DB จะทำให้ข้อมูลใหม่นั้นหาย.
  หาก DB เสียจริง ให้เก็บสำเนา DB ปัจจุบันเพิ่มก่อนและขอเจ้าของงานอนุมัติการ
  restore/merge แยกต่างหาก.

## เกณฑ์ตรวจรอบตามเวลา

1. ดู log ของ scheduler ว่ารอบล่าสุดจบด้วยสรุป `RSS=... Process3=... new=...`
   ไม่ใช่ `give up`. Warning ของ RSS อย่างเดียวไม่เท่ากับทั้งงานล้ม หาก Process3
   ยังดึงและบันทึกได้.
2. ตรวจ `runs` ว่า timestamp ใหม่ขึ้นและจำนวนแถวเพิ่มหนึ่งต่อรอบที่สำเร็จ;
   ตรวจ `PRAGMA integrity_check` ได้ `ok` และจำนวน `ann` ไม่ลดโดยไม่ตั้งใจ.
3. หาก `countbyday=-1` แปลว่ารอบนั้นไม่ได้จำนวนจาก RSS ให้ติดตามรอบถัดไป.
   หาก Process3 ชนเพดาน 20 batch จะมี warning ว่าผลยังไม่ครบประวัติ; อย่าใช้
   การไม่พบรายการเป็นหลักฐานว่าไม่มีประกาศ.

รอบ cron เช้า 2026-09-26 เพิ่ม `runs` ได้หนึ่งแถว, Process3 ดึง 1,001 รายการ
และพบใหม่ 1 รายการ, SQLite integrity `ok`; RSS timeout จึงมี warning และ
`countbyday=-1`. นี่คือ degraded success ไม่ใช่ full-source success.
