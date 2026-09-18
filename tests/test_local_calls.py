"""Named browser calls use synthetic data and temporary local storage only."""
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock

import httpx
import pytest

import local_calls
import main
import playground
from test_browser_voice import new_agent


@pytest.fixture(autouse=True)
def isolated_store(monkeypatch, tmp_path):
    monkeypatch.setattr(local_calls, "DB_PATH", tmp_path / "calls.sqlite3")
    monkeypatch.setattr(local_calls, "PDF_DIR", tmp_path / "pdfs")
    monkeypatch.chdir(tmp_path)


def test_unique_numbers_repeated_names_and_safe_paths():
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(lambda n: local_calls.create(f"SYNTH-{n}", "../Synthetic", 30), range(8)))
    assert len({r["number"] for r in records}) == 8
    assert {r["filename"] for r in records} == {f"{n:03d}Synthetic.pdf" for n in range(1, 9)}
    assert len(local_calls.list_calls()) == 8


@pytest.mark.parametrize("name,age", [("", 20), ("x", -1), ("x", 121), ("x", True), ("x", 1.5), ("x", "20"), ("x\n", 20)])
def test_invalid_identity(name, age):
    with pytest.raises(ValueError):
        local_calls.create("SYNTH", name, age)
    assert local_calls.list_calls() == []


def test_named_pdf_and_download_survive_new_connection(monkeypatch):
    monkeypatch.setattr(playground.llm, "extract", AsyncMock(return_value={"chief_complaint": "Synthetic redness"}))
    async def run():
        agent = new_agent()
        agent.session.update(name="Synthetic", age=31)
        agent.local_record = local_calls.create(agent.session_id, "Synthetic", 31)
        await agent.finalize_slip()
        await agent.finalize_slip()
        records = local_calls.list_calls()
        assert len(records) == 1 and records[0]["status"] == "complete"
        assert records[0]["filename"] == "001Synthetic.pdf"
        assert len(list(local_calls.PDF_DIR.iterdir())) == 1
        assert any(event["type"] == "saved_call" for event in agent.ws.events)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://localhost:8001") as client:
            assert (await client.get("/playground/calls")).json() == records
            response = await client.get("/playground/calls/1/pdf")
            assert response.content.startswith(b"%PDF-")
            assert "001Synthetic.pdf" in response.headers["content-disposition"]
            assert (await client.get("/playground/calls/999/pdf")).status_code == 404
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.phone_app), base_url="http://localhost:8002") as client:
            for path in ("/playground/calls", "/playground/calls/1/pdf"):
                assert (await client.get(path)).status_code == 404
    asyncio.run(run())


@pytest.mark.parametrize("failure", ["extract", "disk"])
def test_failures_never_offer_successful_pdf(monkeypatch, failure):
    monkeypatch.setattr(playground.llm, "extract", AsyncMock(return_value={}))
    if failure == "extract":
        monkeypatch.setattr(playground.llm, "extract", AsyncMock(side_effect=ValueError("synthetic")))
    else:
        monkeypatch.setattr(local_calls, "save_pdf", lambda *args: (_ for _ in ()).throw(OSError("synthetic")))
    async def run():
        agent = new_agent()
        agent.local_record = local_calls.create(agent.session_id, "Synthetic", 30)
        await agent.finish()
        assert local_calls.get(1)["status"] == ("summary_failed" if failure == "extract" else "pdf_failed")
        assert not any(event["type"] == "saved_call" for event in agent.ws.events)
        assert any(event["type"] == "error" for event in agent.ws.events)
    asyncio.run(run())


def test_new_start_snapshots_identity_and_duplicate_start_is_ignored(monkeypatch):
    monkeypatch.setattr(playground, "configuration", lambda: {"voice_ready": True, "text_ready": True})
    async def run():
        agent = new_agent()
        agent.start_background = lambda: None
        await playground._on_text(agent, json.dumps({"event": "start", "name": "First", "age": 20}))
        await playground._on_text(agent, json.dumps({"event": "start", "name": "Second", "age": 40}))
        assert agent.session["name"] == "First" and agent.session["age"] == 20
        assert len(local_calls.list_calls()) == 1
    asyncio.run(run())


def test_disconnected_named_call_is_preserved_without_pdf(monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(playground, "configuration", lambda: {"voice_ready": True, "text_ready": True})
    client = TestClient(main.app, base_url="http://localhost:8001")
    with client.websocket_connect("ws://localhost:8001/playground/stream", headers={"Origin": "http://localhost:8001"}) as socket:
        socket.send_json({"event": "start", "mode": "text", "name": "Synthetic", "age": 40})
        while socket.receive_json()["type"] != "ready":
            pass
    assert local_calls.get(1)["status"] == "interrupted"
    assert not local_calls.PDF_DIR.exists()
