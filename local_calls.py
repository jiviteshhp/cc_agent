"""Persistent register for browser calls and independently numbered phone calls."""
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
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    try:
        with db:
            # Serialize schema upgrades and phone sequence allocation across both
            # ASGI processes; an overlapping call must never reuse a filename.
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS calls (
                number INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL, age INTEGER NOT NULL, created_at TEXT NOT NULL,
                status TEXT NOT NULL, filename TEXT NOT NULL DEFAULT '')""")
            columns = {row[1] for row in db.execute("PRAGMA table_info(calls)")}
            for name, definition in (
                ("source", "TEXT NOT NULL DEFAULT 'browser'"),
                ("phone", "TEXT NOT NULL DEFAULT ''"),
                ("call_index", "INTEGER NOT NULL DEFAULT 0"),
            ):
                if name not in columns:
                    db.execute(f"ALTER TABLE calls ADD COLUMN {name} {definition}")
            db.execute("CREATE TABLE IF NOT EXISTS phone_counters (phone TEXT PRIMARY KEY, last_index INTEGER NOT NULL)")
            # Backfill old registers once, and retain high-water marks after deletion.
            db.execute("""INSERT INTO phone_counters(phone,last_index)
                SELECT phone,MAX(call_index) FROM calls WHERE source='phone' GROUP BY phone
                ON CONFLICT(phone) DO UPDATE SET last_index=MAX(last_index,excluded.last_index)""")
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
    return _record(row) if row else None


def list_calls():
    with _connect() as db:
        return [_record(row) for row in db.execute("SELECT * FROM calls ORDER BY number DESC")]


def _record(row):
    record = dict(row)
    if record["source"] == "phone":
        # Legacy browser schema requires an integer; -1 means unknown, never age 0.
        if record["age"] < 0:
            record["age"] = None
        record["label"] = f"{record['phone'] or 'Unknown caller'}_{record['call_index']}"
    return record


def normalize_phone(raw):
    """Keep full country codes; unprefixed ten-digit numbers use India (+91)."""
    value = (raw or "").strip()
    if not re.fullmatch(r"\+?[0-9 ()-]+", value):
        return ""
    digits = re.sub(r"\D", "", value)
    if value.startswith("00"):
        digits = digits[2:]
    elif not value.startswith("+") and len(digits) == 10:
        digits = "91" + digits
    return "+" + digits if re.fullmatch(r"[1-9][0-9]{6,14}", digits) else ""


def create_phone(raw_phone, name="Unknown", age=None):
    phone = normalize_phone(raw_phone)
    with _connect() as db:
        db.execute("INSERT OR IGNORE INTO phone_counters VALUES (?,0)", (phone,))
        db.execute("UPDATE phone_counters SET last_index=last_index+1 WHERE phone=?", (phone,))
        index = db.execute("SELECT last_index FROM phone_counters WHERE phone=?", (phone,)).fetchone()[0]
        basename = f"{phone or 'unknown'}_{index}"
        sid = "phone_" + basename
        cursor = db.execute("""INSERT INTO calls
            (session_id,name,age,created_at,status,filename,source,phone,call_index)
            VALUES (?,?,?,?,?,?,'phone',?,?)""",
            (sid, name, age if isinstance(age, int) and not isinstance(age, bool) and 0 <= age <= 120 else -1,
             datetime.now().isoformat(timespec="seconds"), "in_call", basename + ".pdf", phone, index))
        number = cursor.lastrowid
    return get(number)


def set_status(number, status):
    with _connect() as db:
        db.execute("UPDATE calls SET status=? WHERE number=?", (status, number))


def save_pdf(record, session, *, update_status=True):
    import pdf_slip
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    target = PDF_DIR / record["filename"]
    temporary = target.with_suffix(".tmp")
    try:
        pdf_slip.generate(session, output_path=str(temporary))
        temporary.replace(target)
        if update_status:
            set_status(record["number"], "complete")
    finally:
        temporary.unlink(missing_ok=True)
    return get(record["number"])


def delete(number):
    """Delete one finished call's live artifacts; never touch backups or other calls.

    Keep the row on disk failure so deletion can be retried. Missing files are OK.
    SQLite serialization protects phone counters and simultaneous delete requests.
    """
    import recorder
    import session_manager
    with _connect() as db:
        row = db.execute("SELECT * FROM calls WHERE number=?", (number,)).fetchone()
        if not row:
            return False
        if row["status"] in {"in_call", "finalizing"}:
            raise ValueError("This call is still active or saving. Wait until it finishes.")
        sid, filename = row["session_id"], row["filename"]
        if Path(sid).name != sid or Path(filename).name != filename:
            raise ValueError("Invalid saved-call path.")
        paths = [PDF_DIR / filename, (PDF_DIR / filename).with_suffix('.tmp')]
        if row["source"] == "phone":
            paths += [Path(session_manager.SESSIONS_DIR) / (sid + '.json'),
                      Path(recorder.RECORDINGS_DIR) / (sid + '.json'),
                      Path(recorder.RECORDINGS_DIR) / (sid + '.wav')]
        for path in paths:
            path.unlink(missing_ok=True)
        db.execute("DELETE FROM calls WHERE number=?", (number,))
    return True
