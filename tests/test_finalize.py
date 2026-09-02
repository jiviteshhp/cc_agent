import asyncio

import main


class SyntheticAgent:
    def __init__(self, chief_complaint=None):
        self.session_id = "SYNTH-CALL-001"
        self.session = {
            "session_id": self.session_id,
            "status": "in_call",
            "chief_complaint": chief_complaint,
        }
        self.recorder = None
        self.stream_closed = False

    async def _close_stream(self):
        self.stream_closed = True

    async def finalize_slip(self):
        if self.session["chief_complaint"] is None:
            self.session["chief_complaint"] = "-"


def _capture_persistence(monkeypatch):
    saved = []
    generated = []
    monkeypatch.setattr(main.session_manager, "save_session", lambda session: saved.append(dict(session)))
    monkeypatch.setattr(main.pdf_slip, "generate", lambda session: generated.append(dict(session)))
    return saved, generated


def test_disconnect_without_complaint_is_saved_as_dropped(monkeypatch):
    saved, generated = _capture_persistence(monkeypatch)
    agent = SyntheticAgent()

    asyncio.run(main._finalize(agent))

    assert agent.stream_closed is True
    assert agent.session["status"] == "dropped"
    assert agent.session["call_end"]
    assert saved[-1]["status"] == "dropped"
    assert generated == []


def test_disconnect_with_complaint_is_saved_as_partial(monkeypatch):
    saved, generated = _capture_persistence(monkeypatch)
    agent = SyntheticAgent(chief_complaint="Eye redness")

    asyncio.run(main._finalize(agent))

    assert agent.session["status"] == "partial"
    assert saved[-1]["status"] == "partial"
    assert generated[-1]["chief_complaint"] == "Eye redness"
