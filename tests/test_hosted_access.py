"""Hosted Host/Origin validation behind the one trusted HTTPS proxy."""
import asyncio

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.websockets import WebSocketDisconnect
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

import main


@pytest.mark.parametrize("host", ["*", "*.example.com", "https://demo.example.com",
                                  "demo.example.com:443", "a/b", "bad_.example.com",
                                  "-bad.example.com", "demo.example.com\nother"])
def test_reject_invalid_hosted_name(monkeypatch, host):
    monkeypatch.setenv("WEB_HOST", host)
    with pytest.raises(ValueError):
        main.local_browser_hosts()


def hosted_app(monkeypatch):
    monkeypatch.setenv("WEB_HOST", "demo.example.com")
    monkeypatch.delenv("LOCAL_DEMO_HOST", raising=False)
    app = FastAPI()
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=main.local_browser_hosts())
    app.middleware("http")(main.local_browser_writes)
    app.include_router(main.playground.router)
    monkeypatch.setattr(main.playground.prompt_store, "update", lambda value: None)
    return ProxyHeadersMiddleware(app, trusted_hosts=["172.30.80.2"])


def test_proxy_preserves_https_origin_and_rejects_spoofing(monkeypatch):
    app = hosted_app(monkeypatch)

    async def run():
        for address in ["172.30.80.2", "198.51.100.10"]:
            transport = httpx.ASGITransport(app=app, client=(address, 1234))
            async with httpx.AsyncClient(transport=transport, base_url="http://demo.example.com") as client:
                headers = {"X-Forwarded-Proto": "https", "Origin": "https://demo.example.com"}
                response = await client.post("/playground/prompts", headers=headers,
                                             json={"conversation": "Synthetic"})
                assert response.status_code == (200 if address == "172.30.80.2" else 403)
                headers["Origin"] = "https://attacker.invalid"
                assert (await client.post("/playground/prompts", headers=headers, json={})).status_code == 403
                assert (await client.get("/playground", headers={"Host": "attacker.invalid"})).status_code == 400
    asyncio.run(run())


def test_secure_websocket_through_trusted_proxy(monkeypatch):
    app = hosted_app(monkeypatch)
    client = TestClient(app, client=("172.30.80.2", 1234))
    headers = {"X-Forwarded-Proto": "https", "Origin": "https://demo.example.com"}
    with client.websocket_connect("ws://demo.example.com/playground/stream", headers=headers):
        pass
    headers["Origin"] = "https://attacker.invalid"
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("ws://demo.example.com/playground/stream", headers=headers):
            pass
