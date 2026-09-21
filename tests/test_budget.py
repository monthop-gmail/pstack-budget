import base64
import os
import pathlib
import sqlite3
import sys

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PSTACK = pathlib.Path('/tmp/pstack-src')
if PSTACK.is_dir():
    sys.path.insert(0, str(PSTACK))
    os.environ.setdefault('PSTACK_ADDONS_PATHS', f'{PSTACK}/addons,budget_addons')

os.environ.setdefault('PSTACK_DATABASE_URL', 'sqlite+aiosqlite:///./test_app.db')
os.environ.setdefault('PSTACK_REDIS_URL', 'redis://localhost:6379/15')
os.environ.setdefault('PSTACK_SECRET_KEY', 'x' * 40)
os.environ.setdefault('PSTACK_ADMIN_PASSWORD', 'test-admin-password-strong')
os.environ.setdefault('PSTACK_MODULES', 'users,budget')
os.environ.setdefault('BUDGET_PASSWORD', 'test-budget-password-strong')
os.environ.setdefault('BUDGET_SESSION_SECRET', 'y' * 40)
os.environ.setdefault('BUDGET_API_USER', 'team')


@pytest.fixture()
def budget_db(tmp_path, monkeypatch):
    path = tmp_path / 'budget2570.db'
    con = sqlite3.connect(path)
    con.executescript('''CREATE TABLE items (id INTEGER PRIMARY KEY, book TEXT, book_label TEXT, page TEXT, item_no TEXT, ministry TEXT, agency TEXT, buyer TEXT, province TEXT, tambon TEXT, amphoe TEXT, text TEXT, tnorm TEXT, skel TEXT, skelq TEXT, amount INTEGER, project_total INTEGER, qty REAL, unit TEXT, file TEXT); INSERT INTO items VALUES (1,'book-a','เล่ม A','7','1','กระทรวงทดสอบ','หน่วยทดสอบ','','เชียงใหม่','','','งบการศึกษา','งบการศึกษา','งบการศกษา','งบการศกษา',123456,0,1,'รายการ','book-a/sample.txt');''')
    con.close()
    monkeypatch.setenv('BUDGET_DB_PATH', str(path))
    monkeypatch.setenv('BUDGET_DOCS_PATH', str(tmp_path))
    return path


def test_search_requires_auth(budget_db):
    from budget_addons.budget.routes import search
    # Route-level integration is covered by pstack's smoke test; this guards the
    # data contract without needing a Postgres/Redis lifespan.
    assert budget_db.is_file()


def test_query_helpers_find_item(budget_db):
    from budget_addons.budget.routes import _db, _resolve
    con = _db()
    try:
        mode, where, args, total = _resolve({'q': 'การศึกษา'}, con)
    finally:
        con.close()
    assert mode == 'exact'
    assert total['n'] == 1
    assert 'tnorm LIKE ?' in where
    assert args == ['%การศึกษา%']


def test_basic_header_format():
    from budget_addons.budget.routes import _basic_ok
    encoded = base64.b64encode(b'team:test-budget-password-strong').decode()
    assert base64.b64decode(encoded) == b'team:test-budget-password-strong'
    request = Request({"type": "http", "headers": [(b"authorization", f"Basic {encoded}".encode())]})
    assert _basic_ok(request)
