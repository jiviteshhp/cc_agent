# Session store: one JSON file per call under sessions/.

import json
import os
import re
from datetime import datetime

SESSIONS_DIR = "sessions"

# Full schema. New sessions start with these keys.
FIELDS = [
    "session_id", "name", "age", "uhid", "phone", "created_at",
    "call_start", "call_end", "status", "chief_complaint",
    "chief_complaint_branch", "laterality", "duration",
    "dynamic_follow_up", "prior_treatment", "comorbidities",
    "medications",
]


def ensure_dir():
    os.makedirs(SESSIONS_DIR, exist_ok=True)


def _path(session_id):
    return os.path.join(SESSIONS_DIR, f"{session_id}.json")


def _normalize(phone):
    # Compare on the last 10 digits, ignoring +, spaces, country code.
    digits = re.sub(r"\D", "", phone or "")
    return digits[-10:] if len(digits) > 10 else digits


def _store_format(phone):
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 10:
        return "+91" + digits
    if len(digits) == 12 and digits.startswith("91"):
        return "+" + digits
    return phone if phone.startswith("+") else "+" + digits


def generate_session_id():
    ensure_dir()
    today = datetime.now().strftime("%Y%m%d")
    counter = 0
    for fn in os.listdir(SESSIONS_DIR):
        m = re.match(rf"{today}-(\d+)\.json$", fn)
        if m:
            counter = max(counter, int(m.group(1)))
    return f"{today}-{counter + 1:04d}"


def new_session(name, age, uhid, phone):
    ensure_dir()
    data = {f: None for f in FIELDS}
    data.update({
        "session_id": generate_session_id(),
        "name": name,
        "age": age,
        "uhid": uhid,
        "phone": _store_format(phone),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "status": "registered",
    })
    save_session(data)
    return data


def load_session(session_id):
    with open(_path(session_id), "r", encoding="utf-8") as f:
        return json.load(f)


def save_session(data):
    ensure_dir()
    with open(_path(data["session_id"]), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def find_session_by_phone(phone):
    # Scan sessions for a matching phone. Prefer an open (registered) session,
    # then the most recently created one.
    ensure_dir()
    target = _normalize(phone)
    if not target:
        return None
    matches = []
    for fn in os.listdir(SESSIONS_DIR):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(SESSIONS_DIR, fn), "r", encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        if _normalize(d.get("phone", "")) == target:
            matches.append(d)
    if not matches:
        return None
    registered = [m for m in matches if m.get("status") == "registered"]
    pool = registered or matches
    pool.sort(key=lambda m: m.get("created_at") or "", reverse=True)
    return pool[0]
