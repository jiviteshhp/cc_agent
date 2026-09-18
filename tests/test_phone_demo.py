"""Hotspot HTTPS checks with temporary certificates, no provider calls."""
import asyncio
import subprocess

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.websockets import WebSocketDisconnect

import main
from scripts.phone_demo import prepare_certificates, private_ipv4


@pytest.mark.parametrize("host", ["0.0.0.0", "127.0.0.1", "8.8.8.8", "*", "localhost", "https://192.168.1.2", "::1", "169.254.1.2"])
def test_reject_non_private_bind_and_host(host, monkeypatch):
    with pytest.raises(ValueError):
        private_ipv4(host)
    monkeypatch.setenv("LOCAL_DEMO_HOST", host)
    with pytest.raises(ValueError):
        main.local_browser_hosts()


def test_host_opt_in_is_exact_and_default_remains_local(monkeypatch):
    monkeypatch.delenv("LOCAL_DEMO_HOST", raising=False)
    assert main.local_browser_hosts() == ["localhost", "127.0.0.1", "[::1]"]
    monkeypatch.setenv("LOCAL_DEMO_HOST", "192.168.43.20")
    assert main.local_browser_hosts() == ["localhost", "127.0.0.1", "[::1]", "192.168.43.20"]


def test_real_certificate_chain_ip_and_key_permissions(tmp_path):
    key, cert, ca = prepare_certificates("192.168.43.20", tmp_path)
    root_before = ca.read_bytes()
    assert key.stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "ca.key").stat().st_mode & 0o777 == 0o600
    assert tmp_path.stat().st_mode & 0o777 == 0o700
    wrong_ip = subprocess.run(["openssl", "verify", "-CAfile", str(ca), "-verify_ip", "192.168.43.21", str(cert)], capture_output=True)
    assert wrong_ip.returncode != 0
    prepare_certificates("192.168.43.21", tmp_path)
    assert ca.read_bytes() == root_before  # DHCP change needs no new phone trust anchor.


def test_https_http_and_websocket_keep_same_origin_checks(monkeypatch):
    monkeypatch.setenv("LOCAL_DEMO_HOST", "192.168.43.20")
    app = FastAPI()
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=main.local_browser_hosts())
    app.middleware("http")(main.local_browser_writes)
    app.include_router(main.playground.router)
    origin = "https://192.168.43.20:8443"
    monkeypatch.setattr(main.playground.prompt_store, "update", lambda value: None)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
            assert (await client.get("/playground")).status_code == 200
            assert (await client.get("/playground", headers={"Host": "192.168.43.21:8443"})).status_code == 400
            for source, status in [(origin, 200), ("http://192.168.43.20:8443", 403), ("https://attacker.invalid", 403)]:
                response = await client.post("/playground/prompts", headers={"Origin": source}, json={"conversation": "Synthetic"})
                assert response.status_code == status
    asyncio.run(run())
    client = TestClient(app)
    with client.websocket_connect("wss://192.168.43.20:8443/playground/stream", headers={"Origin": origin}):
        pass
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("wss://192.168.43.20:8443/playground/stream", headers={"Origin": "https://attacker.invalid"}):
            pass
