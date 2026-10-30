"""Synthetic phone history, with no provider traffic or real patient data."""
import asyncio
import io
import sqlite3
import wave
from urllib.parse import unquote
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient

import call_access
import local_calls
import main
import recorder
import session_manager

PHONE = "+919000000001"


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(local_calls, "DB_PATH", tmp_path / "calls.sqlite3")
    monkeypatch.setattr(local_calls, "PDF_DIR", tmp_path / "pdfs" / "saved")
    monkeypatch.setattr(session_manager, "SESSIONS_DIR", "sessions")


def test_phone_count_is_atomic_persistent_and_independent_of_browser():
    local_calls.create("browser-synthetic", "Synthetic", 30)
    with ThreadPoolExecutor(max_workers=4) as pool:
        calls = list(pool.map(lambda _: local_calls.create_phone(PHONE), range(8)))
    assert sorted(c["call_index"] for c in calls) == list(range(1, 9))
    assert len({c["session_id"] for c in calls}) == 8
    assert local_calls.create_phone("90000 00001")["label"] == PHONE + "_9"
    assert local_calls.create_phone("0091 9000000001")["filename"] == PHONE + "_10.pdf"
    assert local_calls.create_phone("+449000000001")["call_index"] == 1
    assert local_calls.get(1)["filename"] == "001Synthetic.pdf"


def test_unknown_callers_have_safe_distinct_labels_without_fake_demographics():
    one = local_calls.create_phone("anonymous")
    two = local_calls.create_phone("../../unknown")
    assert one["label"] == "Unknown caller_1"
    assert two["label"] == "Unknown caller_2"
    assert one["age"] is None and one["phone"] == ""
    assert two["filename"] == "unknown_2.pdf"


def test_existing_browser_database_upgrades_without_losing_entries():
    with sqlite3.connect(local_calls.DB_PATH) as db:
        db.execute("""CREATE TABLE calls(number INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT UNIQUE NOT NULL, name TEXT NOT NULL, age INTEGER NOT NULL,
            created_at TEXT NOT NULL, status TEXT NOT NULL, filename TEXT NOT NULL DEFAULT '')""")
        db.execute("INSERT INTO calls VALUES(7,'old','Synthetic',42,'2026-01-01','complete','007Synthetic.pdf')")
    assert local_calls.get(7)["source"] == "browser"
    assert local_calls.create_phone(PHONE)["number"] == 8
    assert local_calls.get(7)["filename"] == "007Synthetic.pdf"


def test_repeat_phone_calls_never_reuse_session_or_old_clinical_details():
    registration = session_manager.new_session("Synthetic", 40, "test", PHONE)
    first = session_manager.new_phone_session(PHONE)
    first.update(status="complete", chief_complaint="Synthetic old detail")
    session_manager.save_session(first)
    second = session_manager.new_phone_session(PHONE)
    assert second["session_id"] != first["session_id"]
    assert second["call_label"] == PHONE + "_2"
    assert second["chief_complaint"] is None
    assert second["name"] == "Synthetic" and second["age"] == 40
    assert session_manager.load_session(first["session_id"]) == first
    assert session_manager.load_session(registration["session_id"]) == registration


class SyntheticPhoneAgent:
    def __init__(self, ws, session):
        self.ws, self.session = ws, session
        self.session_id = session["session_id"]
        self.stream_id = None
        self._closed = False
        self.recorder = None

    async def _close_stream(self):
        self.recorder.add_inbound(b"\x10\x00" * 800)
        self.recorder.add_outbound(b"\x20\x00" * 800)
        self.recorder.user_turn("Synthetic patient response")
        self.recorder.agent_turn("Synthetic assistant response")

    async def finalize_slip(self):
        self.session["chief_complaint"] = "Synthetic redness"


def test_incoming_calls_appear_on_website_with_transcript_and_one_channel_audio(monkeypatch):
    monkeypatch.setattr(main, "ConversationAgent", SyntheticPhoneAgent)
    client = TestClient(main.phone_app)
    for _ in range(2):
        ticket = call_access.issue_ticket(PHONE)
        with client.websocket_connect("/stream?ticket=" + ticket):
            pass
    assert [c["call_index"] for c in local_calls.list_calls()] == [2, 1]

    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://localhost") as web:
            calls = (await web.get("/playground/calls")).json()
            assert len(calls) == 2
            for c in calls:
                assert c["audio_available"] and c["status"] == "partial"
                review = await web.get(f"/calls/{c['session_id']}")
                assert c["label"] in review.text
                assert "Synthetic patient response" in review.text
                assert "Synthetic assistant response" in review.text
                response = await web.get(f"/calls/{c['session_id']}/audio")
                assert c["label"] + ".wav" in unquote(response.headers["content-disposition"])
                with wave.open(io.BytesIO(response.content), "rb") as wav:
                    assert wav.getnchannels() == 1
                    assert wav.getframerate() == 8000
                    assert wav.getnframes() >= 800
                assert (await web.get(f"/playground/calls/{c['number']}/pdf")).content.startswith(b"%PDF")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.phone_app), base_url="https://tunnel.invalid") as phone:
            for path in ("/playground/calls", f"/calls/{calls[0]['session_id']}", f"/calls/{calls[0]['session_id']}/audio"):
                assert (await phone.get(path)).status_code == 404
    asyncio.run(check())


@pytest.mark.parametrize("failure", ["summary", "pdf", "recording"])
def test_recording_survives_summary_pdf_failure_and_recording_failure_is_visible(monkeypatch, failure):
    agent = SyntheticPhoneAgent(None, session_manager.new_phone_session(PHONE))
    agent.recorder = recorder.CallRecorder(agent.session_id)
    if failure == "summary":
        agent._extraction_failed = True
    elif failure == "pdf":
        monkeypatch.setattr(local_calls, "save_pdf", lambda *a: (_ for _ in ()).throw(OSError("synthetic")))
    else:
        monkeypatch.setattr(agent.recorder, "finalize", lambda *a: (_ for _ in ()).throw(OSError("synthetic")))
    asyncio.run(main._finalize(agent))
    assert local_calls.get(1)["status"] == {"summary": "summary_failed", "pdf": "pdf_failed", "recording": "recording_failed"}[failure]
    if failure != "recording":
        from pathlib import Path
        assert (Path("recordings") / (agent.session_id + ".wav")).is_file()
        assert (Path("recordings") / (agent.session_id + ".json")).is_file()
