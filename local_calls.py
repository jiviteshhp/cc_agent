"""Persistent register for named localhost browser calls."""
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DB_PATH = Path("state/browser_calls.sqlite3")
PDF_DIR = Path("pdfs/local_calls")


@contextmanager
def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS calls (
        number INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL, age INTEGER NOT NULL, created_at TEXT NOT NULL,
        status TEXT NOT NULL, filename TEXT NOT NULL DEFAULT '')""")
    try:
        with db:
            yield db
    finally:
        db.close()


def validate(name, age):
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise ValueError("Enter a name of 1–80 characters.")
    if any(ord(char) < 32 for char in name):
        raise ValueError("Name cannot contain control characters.")
    if isinstance(age, bool) or not isinstance(age, int) or not 0 <= age <= 120:
        raise ValueError("Enter a whole-number age from 0 to 120.")
    return name.strip(), age


def create(session_id, name, age):
    name, age = validate(name, age)
    with _connect() as db:
        cursor = db.execute(
            "INSERT INTO calls(session_id,name,age,created_at,status) VALUES (?,?,?,?,?)",
            (session_id, name, age, datetime.now().isoformat(timespec="seconds"), "in_call"))
        number = cursor.lastrowid
        safe_name = re.sub(r"[^\w-]", "", name, flags=re.UNICODE).strip("_") or "person"
        filename = f"{number:03d}{safe_name}.pdf"
        db.execute("UPDATE calls SET filename=? WHERE number=?", (filename, number))
    return get(number)


def get(number):
    with _connect() as db:
        row = db.execute("SELECT * FROM calls WHERE number=?", (number,)).fetchone()
    return dict(row) if row else None


def list_calls():
    with _connect() as db:
        return [dict(row) for row in db.execute("SELECT * FROM calls ORDER BY number DESC")]


def set_status(number, status):
    with _connect() as db:
        db.execute("UPDATE calls SET status=? WHERE number=?", (status, number))


def save_pdf(record, session):
    import pdf_slip
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    target = PDF_DIR / record["filename"]
    temporary = target.with_suffix(".tmp")
    try:
        pdf_slip.generate(session, output_path=str(temporary))
        temporary.replace(target)
        set_status(record["number"], "complete")
    finally:
        temporary.unlink(missing_ok=True)
    return get(record["number"])
