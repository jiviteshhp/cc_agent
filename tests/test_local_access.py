import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import call_access
import main

SECRET = "synthetic-callback-secret-for-offline-tests"


def test_local_pages_need_no_login_and_account_routes_are_gone(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),
                                    base_url="http://localhost:8001") as client:
            for path in ("/", "/calls", "/playground"):
                response = await client.get(path)
                assert response.status_code == 200
                assert "set-cookie" not in response.headers
                assert "Founder dashboard" not in response.text
            for path in ("/login", "/logout", "/calls/control"):
                response = await client.post(path, headers={"Origin": "http://localhost:8001"})
                assert response.status_code in (404, 405)
            response = await client.get("/", headers={"Host": "attacker.invalid"})
            assert response.status_code == 400

    asyncio.run(run())


@pytest.mark.parametrize("path", ["/", "/calls", "/recordings/synthetic.wav",
                                  "/playground", "/docs", "/openapi.json", "/login"])
def test_tunnel_app_has_no_website_routes(path):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.phone_app),
                                    base_url="https://tunnel.test.invalid") as client:
            assert (await client.get(path)).status_code == 404

    asyncio.run(run())


def test_local_prompt_writes_require_same_origin(monkeypatch):
    updates = []
    monkeypatch.setattr(main.playground.prompt_store, "update", updates.append)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),
                                    base_url="http://localhost:8001") as client:
            for headers in ({}, {"Origin": "https://attacker.invalid"}):
                response = await client.post("/playground/prompts", json={"conversation": "synthetic"},
                                             headers=headers)
                assert response.status_code == 403
            response = await client.post("/playground/prompts", json={"conversation": "synthetic"},
                                         headers={"Origin": "http://localhost:8001"})
            assert response.status_code == 200
            assert updates == ["synthetic"]

    asyncio.run(run())


def test_playground_socket_is_local_same_origin_without_password():
    client = TestClient(main.app, base_url="http://localhost:8001")
    for headers in ({}, {"Origin": "https://attacker.invalid"}):
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("ws://localhost:8001/playground/stream", headers=headers):
                pass
    with client.websocket_connect("ws://localhost:8001/playground/stream",
                                  headers={"Origin": "http://localhost:8001"}):
        pass


def test_phone_callback_secret_and_ticket_without_call_toggle(monkeypatch):
    monkeypatch.setenv("VOBIZ_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("SERVER_HOST", "tunnel.test.invalid")
    monkeypatch.setattr(call_access, "_tickets", {})

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.phone_app),
                                    base_url="https://tunnel.test.invalid") as client:
            assert (await client.post("/answer")).status_code == 403
            response = await client.post("/answer", params={"key": SECRET}, data={"From": "synthetic-phone"})
            assert response.status_code == 200
            assert "<Stream" in response.text and "<Hangup" not in response.text
            assert "synthetic-phone" not in response.text
            token = response.text.split("?ticket=")[1].split()[0]
            assert call_access.redeem_ticket(token) == "synthetic-phone"
            assert call_access.redeem_ticket(token) is None

    asyncio.run(run())


def test_ticket_expiry_capacity_and_unauthorized_socket(monkeypatch):
    monkeypatch.setattr(call_access, "_tickets", {})
    now = [100.0]
    monkeypatch.setattr(call_access.time, "monotonic", lambda: now[0])
    token = call_access.issue_ticket("synthetic-phone")
    now[0] += 61
    assert call_access.redeem_ticket(token) is None
    for _ in range(call_access._MAX_PENDING + 10):
        call_access.issue_ticket("synthetic-phone")
    assert len(call_access._tickets) == call_access._MAX_PENDING
    # Restore the real monotonic clock before using the async test client.
    monkeypatch.undo()
    client = TestClient(main.phone_app)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/stream?ticket=invalid"):
            pass


@pytest.mark.parametrize("host", ["", "localhost:8002", "https://tunnel.test.invalid"])
def test_missing_tunnel_host_is_a_clear_setup_error(monkeypatch, host):
    monkeypatch.setenv("SERVER_HOST", host)
    monkeypatch.setenv("VOBIZ_WEBHOOK_SECRET", SECRET)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.phone_app),
                                    base_url="https://tunnel.test.invalid") as client:
            response = await client.post("/answer", params={"key": SECRET})
            assert response.status_code == 503
            assert "SERVER_HOST" in response.text

    asyncio.run(run())


def test_stored_values_are_escaped():
    html = main._render_call_detail("synthetic", None, {
        "name": "<script>alert(1)</script>", "chief_complaint": "<img onerror=alert(1)>"})
    assert "<script>alert(1)</script>" not in html
    assert "<img onerror" not in html
    assert "&lt;script&gt;" in html
