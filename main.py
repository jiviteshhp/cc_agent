# Local website (app, port 8001) and tunnel-facing phone endpoints (phone_app,
# port 8002). Default to loopback; phone_demo.py opts into private hotspot HTTPS.
# Tunnel ONLY port 8002. See README.md.

import base64
import json
import os
import re
import hmac
import ipaddress
from contextlib import asynccontextmanager
from datetime import datetime
from html import escape

from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import FileResponse, HTMLResponse, Response
from starlette.middleware.trustedhost import TrustedHostMiddleware

load_dotenv()

import pdf_slip
import session_manager
import llm
import playground
import recorder
import call_access
import local_calls
from agent import ConversationAgent


@asynccontextmanager
async def lifespan(app):
    os.makedirs("sessions", exist_ok=True)
    os.makedirs("pdfs", exist_ok=True)
    os.makedirs("recordings", exist_ok=True)
    if playground.configuration()["text_ready"]:
        try:
            await llm.warm()
            print("[warm] llm ready")
        except Exception as exc:
            print(f"[warm] unavailable: {type(exc).__name__}")
    else:
        print("[warm] skipped: add GEMINI_API_KEY to .env for live conversations")
    if playground.configuration()['s2s_ready']:
        try:
            import s2s
            import prompt_store
            await s2s.prepare_first_message(prompt_store.saved_first_message())
            print('[warm] native first message ready')
        except Exception as exc:
            print(f'[warm] native first message unavailable: {type(exc).__name__}')
    if app is phone_app and os.getenv('PHONE_VOICE_ENGINE', 'cascaded').strip().lower() == 'cascaded':
        import filler_audio
        count = await filler_audio.prepare_all()
        print(f'[warm] phone fillers ready: {count}/{len(filler_audio.PHRASES)}')
    print("server ready")
    yield


app = FastAPI(lifespan=lifespan)


def local_browser_hosts():
    hosts = ["localhost", "127.0.0.1", "[::1]"]
    extra = os.getenv("LOCAL_DEMO_HOST", "").strip()
    if extra:
        address = ipaddress.IPv4Address(extra)
        if not any(address in ipaddress.ip_network(network) for network in
                   ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")):
            raise ValueError("LOCAL_DEMO_HOST must be a private LAN IPv4 address")
        hosts.append(str(address))
    hosted = os.getenv("WEB_HOST", "").strip().lower()
    if hosted:
        # Opt in to exactly one DNS name; no schemes, ports or wildcards.
        labels = hosted.split(".")
        if (len(hosted) > 253 or len(labels) < 2 or
                any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                    for label in labels)):
            raise ValueError("WEB_HOST must be one DNS hostname without scheme, port or path")
        hosts.append(hosted)
    return hosts


app.add_middleware(TrustedHostMiddleware, allowed_hosts=local_browser_hosts())
app.include_router(playground.router)   # /playground tester (isolated from calls)
# This app has no website, recordings, prompt editor or API docs to expose.
phone_app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def local_browser_writes(request: Request, call_next):
    # Localhost still needs CSRF protection: an unrelated website must not be
    # able to edit prompts on a local server. No account/password is involved.
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        expected = f"{request.url.scheme}://{request.headers.get('host', '')}"
        if request.headers.get("origin") != expected:
            return Response("Untrusted origin", status_code=403)
    return await call_next(request)


@app.get("/healthz")
@phone_app.get("/healthz")
async def healthz():
    # Liveness only; provider availability is measured by synthetic calls.
    return {"status": "ok"}


@phone_app.post("/answer")
async def answer(request: Request):
    # The tunnel is public even though the app runs locally. Keep the callback
    # secret to prevent outsiders opening billable voice sessions.
    secret = os.getenv("VOBIZ_WEBHOOK_SECRET", "")
    if len(secret) < 32:
        return Response("Call transport is not configured", status_code=503)
    supplied = request.query_params.get("key", "")
    if not hmac.compare_digest(secret.encode(), supplied.encode()):
        return Response(status_code=403)
    form = await request.form()
    caller = form.get("From", "")
    host = os.getenv("SERVER_HOST", "").strip()
    if not host or host.startswith(("localhost", "127.0.0.1")) or "/" in host:
        return Response("Set SERVER_HOST to the public tunnel hostname", status_code=503)
    ticket = call_access.issue_ticket(str(caller))
    input_rate = 16000 if os.getenv("PHONE_VOICE_ENGINE", "cascaded").strip().lower() == "s2s" else 8000
    # Only documented Vobiz attributes. The former noiseCancellation/Level
    # flags are not in its Stream reference; don't promise unverified DSP.
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        "    <Stream\n"
        '        bidirectional="true"\n'
        '        keepCallAlive="true"\n'
        '        audioTrack="inbound"\n'
        f'        contentType="audio/x-l16;rate={input_rate}">\n'
        f"        wss://{escape(host)}/stream?ticket={ticket}\n"
        "    </Stream>\n"
        "    <Hangup/>\n"
        "</Response>"
    )
    return Response(content=xml, media_type="application/xml")


@phone_app.websocket("/stream")
async def stream(websocket: WebSocket):
    raw_phone = call_access.redeem_ticket(websocket.query_params.get("ticket", ""))
    if raw_phone is None:
        await websocket.close(code=4403)
        return
    # Snapshot the configured engine once; an active call never changes engines.
    engine = os.getenv("PHONE_VOICE_ENGINE", "cascaded").strip().lower()
    if engine not in {"cascaded", "s2s"}:
        await websocket.close(code=1011)
        return
    await websocket.accept()
    session_data = session_manager.new_phone_session(raw_phone)

    if engine == "s2s":
        from s2s import GeminiPhoneAgent
        agent = GeminiPhoneAgent(websocket, session_data)
    else:
        agent = ConversationAgent(websocket, session_data)
        agent.session["voice_engine"] = "cascaded"
    agent.recorder = recorder.CallRecorder(agent.session_id)
    print(f"[phone] call connected (engine={engine})")
    try:
        while True:
            msg = await websocket.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                if agent.stream_id and not agent._closed:
                    await agent.on_audio(msg["bytes"])
            elif msg.get("text") is not None:
                await _on_text(agent, msg["text"])
    except Exception as e:
        print(f"[{agent.session_id}] ws ended: {e}")
    finally:
        await _finalize(agent)


async def _on_text(agent, text):
    try:
        data = json.loads(text)
    except ValueError:
        print(f"[{agent.session_id}] non-JSON text frame: {text[:100]}")
        return
    event = data.get("event")
    if event == "start":
        if agent.stream_id:
            return                    # format/stream identity cannot change mid-call
        s = data.get("start", {})
        fmt = s.get("mediaFormat") or {}
        # Validate the selected engine's real input format. Reject a
        # negotiated mismatch instead of feeding incorrectly labelled ASR audio.
        if (not s.get("streamId")
                or fmt.get("encoding") != "audio/x-l16"
                or str(fmt.get("sampleRate")) != str(getattr(agent, "input_rate", 8000))
                or str(fmt.get("channels", 1)) != "1"
                or s.get("tracks", ["inbound"]) != ["inbound"]):
            print(f"[{agent.session_id}] unsupported inbound audio format/track")
            agent._closed = True
            await agent.ws.close(code=1003)
            return
        agent.stream_id = s["streamId"]
        print(f"[{agent.session_id}] start event, stream_id={agent.stream_id}")
        # Task so the receive loop keeps draining frames during playback.
        agent.start_background()
    elif event in ("media", "audio"):
        media = data.get("media") or data.get("audio") or {}
        if not agent.stream_id or media.get("track", "inbound") != "inbound":
            return
        payload = media.get("payload", "")
        if payload:
            raw = base64.b64decode(payload, validate=True)
            if len(raw) % 2:
                raise ValueError("Incomplete 16-bit PCM sample")
            await agent.on_audio(raw)
    elif event == "stop":
        print(f"[{agent.session_id}] stop event received")
    elif event == "playedStream":
        agent.playback_finished(data.get("name"))
    elif event in ("clearedAudio", "mark", "dtmf"):
        pass   # Vobiz acks / signals we don't act on; not errors
    else:
        print(f"[{agent.session_id}] unknown event '{event}': {str(data)[:200]}")


@app.get("/")
async def local_home():
    return await playground.playground_page()


@app.get("/calls", response_class=HTMLResponse)
async def calls_page():
    sessions = []
    if os.path.isdir("sessions"):
        for fn in os.listdir("sessions"):
            if fn.endswith(".json"):
                try:
                    with open(os.path.join("sessions", fn), encoding="utf-8") as f:
                        sessions.append(json.load(f))
                except Exception:
                    pass
    sessions.sort(key=lambda s: s.get("call_start") or s.get("created_at") or "",
                  reverse=True)
    colors = {"complete": "#2a7a4b", "partial": "#d68910", "dropped": "#c0392b",
              "in_call": "#1a6db5", "registered": "#666"}
    fields = [("Chief complaint", "chief_complaint"), ("Eye", "laterality"),
              ("Duration", "duration"), ("Follow-up", "dynamic_follow_up"),
              ("Prior Tx", "prior_treatment"), ("Comorbid", "comorbidities"),
              ("Meds", "medications")]

    def cell(v):
        if not v or v == "-":
            return "<td style='color:#bbb'>—</td>"
        c = "#c0392b" if v == "unclear" else "inherit"
        return f"<td style='color:{c}'>{escape(str(v))}</td>"

    rows = ""
    for s in sessions:
        st = s.get("status", "")
        sc = colors.get(st, "#666")
        phone = escape(str(s.get("call_label") or s.get("phone") or "—"))
        ts = (s.get("call_start") or s.get("created_at") or "")[:16].replace("T", " ")
        sid = escape(str(s.get("session_id", "")), quote=True)
        rows += (f"<tr><td><a href='/calls/{sid}'><b>{phone}</b></a></td><td>{escape(str(s.get('name','')))}</td>"
                 f"<td><span style='color:{sc};font-weight:600'>{escape(str(st))}</span></td>"
                 f"<td style='color:#888;font-size:11px'>{escape(ts)}</td>")
        for _, k in fields:
            rows += cell(s.get(k))
        rows += f"<td style='color:#888;font-size:11px'>{sid}</td></tr>\n"
    head = "".join(f"<th>{lbl}</th>" for lbl, _ in fields)
    agg = _recordings_aggregate()
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="10"><title>CC Agent</title><style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:13px;background:#f7f7f7;padding:24px}}
h2{{margin-bottom:16px;font-size:18px;color:#222}}
table{{border-collapse:collapse;width:100%;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.08)}}
th,td{{padding:8px 12px;text-align:left;border-bottom:1px solid #f0f0f0;white-space:nowrap}}
th{{background:#fafafa;font-weight:600;color:#555;font-size:11px;text-transform:uppercase;letter-spacing:.5px}}
tr:hover td{{background:#fafffe}}
a{{color:#1a6db5;text-decoration:none}} a:hover{{text-decoration:underline}}
.agg{{color:#666;font-size:12px;margin-bottom:14px}}
</style></head><body>
<p style="margin-bottom:16px"><a href="/playground">Voice / text playground</a> · Local testing only</p>
<h2>CC Agent &mdash; {len(sessions)} call{"s" if len(sessions)!=1 else ""} (auto-refresh 10s)</h2>
<div class="agg">{agg}</div>
<table><tr><th>Phone</th><th>Name</th><th>Status</th><th>Time</th>{head}<th>Session ID</th></tr>
{rows}</table></body></html>"""


SLIP_LABELS = [("Chief complaint", "chief_complaint"), ("Eye", "laterality"),
               ("Duration", "duration"), ("Follow-up", "dynamic_follow_up"),
               ("Prior treatment", "prior_treatment"), ("Comorbidities", "comorbidities"),
               ("Medications", "medications"), ("Additional details", "additional_details"),
               ("Uncertainties", "uncertainties")]


def _recordings_aggregate():
    # One-line latency rollup across all recorded calls for the /calls header.
    medians = []
    n = 0
    if os.path.isdir("recordings"):
        for fn in os.listdir("recordings"):
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join("recordings", fn), encoding="utf-8") as f:
                    summ = json.load(f).get("summary") or {}
            except Exception:
                continue
            n += 1
            lat = summ.get("turn_latency_ms") or {}
            if lat.get("median") is not None:
                medians.append(lat["median"])
    if n == 0:
        return "No recordings yet."
    if not medians:
        return f"{n} recorded call{'s' if n != 1 else ''} · no latency captured yet"
    avg = int(sum(medians) / len(medians))
    return (f"{n} recorded call{'s' if n != 1 else ''} · "
            f"avg median turn latency {avg} ms")


@app.get("/recordings/{name}")
async def recording_audio(name: str):
    path = os.path.join("recordings", os.path.basename(name))
    if not os.path.isfile(path):
        return Response(status_code=404)
    return FileResponse(path, media_type="audio/wav")


@app.get("/calls/{session_id}", response_class=HTMLResponse)
async def call_detail(session_id: str):
    sid = os.path.basename(session_id)
    rec = None
    rpath = os.path.join("recordings", f"{sid}.json")
    if os.path.isfile(rpath):
        try:
            with open(rpath, encoding="utf-8") as f:
                rec = json.load(f)
        except Exception:
            rec = None
    try:
        sess = session_manager.load_session(sid)
    except Exception:
        sess = None
    if rec is None and sess is None:
        return Response(status_code=404)
    return _render_call_detail(sid, rec, sess)


def _render_call_detail(sid, rec, sess):
    sid = escape(str(sid), quote=True)
    base = rec or sess or {}
    name = escape(str(base.get("name") or "—"))
    phone = escape(str(base.get("call_label") or base.get("phone") or "—"))
    status = escape(str(base.get("status") or "—"))

    if rec and rec.get("audio"):
        audio_html = (f"<audio id='player' controls preload='metadata' "
                      f"src='/recordings/{escape(str(rec['audio']), quote=True)}' style='width:100%'></audio>"
                      f"<div class='hint'>One mono recording · caller and assistant together · click a turn to jump</div>"
                      f"<p><a href='/calls/{sid}/audio'>Download recording</a></p>")
    else:
        audio_html = "<div class='hint'>No audio recorded for this call.</div>"

    summ = (rec or {}).get("summary") or {}
    lat = summ.get("turn_latency_ms") or {}
    cards = [("Duration", f"{summ.get('duration_s', '—')}s"),
             ("Turns", summ.get("n_turns", "—")),
             ("Barge-ins", summ.get("n_barge_ins", "—")),
             ("Median latency", f"{lat.get('median', '—')} ms"),
             ("P90 latency", f"{lat.get('p90', '—')} ms"),
             ("Avg LLM 1st token", f"{summ.get('avg_llm_ttft_ms', '—')} ms"),
             ("Avg TTS synth", f"{summ.get('avg_tts_first_ms', '—')} ms")]
    cards_html = "".join(
        f"<div class='card'><div class='cv'>{escape(str(v))}</div><div class='cl'>{l}</div></div>"
        for l, v in cards)

    turns_html = ""
    for t in (rec or {}).get("turns", []):
        cls = "user" if t.get("role") == "user" else "bot"
        secs = t.get("t") or 0
        ts = f"{int(secs // 60)}:{int(secs % 60):02d}"
        badge = ""
        if t.get("role") == "assistant":
            bits = []
            if t.get("latency_ms") is not None:
                bits.append(f"{t['latency_ms']}ms")
            if t.get("llm_ttft_ms") is not None:
                bits.append(f"llm {t['llm_ttft_ms']}ms")
            if t.get("tts_first_ms") is not None:
                bits.append(f"tts {t['tts_first_ms']}ms")
            if t.get("interrupted"):
                bits.append("interrupted")
            if bits:
                badge = f"<div class='badge'>{' · '.join(bits)}</div>"
        text = escape(str(t.get("text") or ""))
        turns_html += (f"<div class='turn {cls}' onclick='seek({secs})'>"
                       f"<span class='ts'>{ts}</span> {text}{badge}</div>")
    if not turns_html:
        turns_html = "<div class='hint'>No transcript for this call.</div>"

    slip = (rec or {}).get("slip") or {k: (sess or {}).get(k) for _, k in SLIP_LABELS}
    slip_rows = ""
    for label, k in SLIP_LABELS:
        v = slip.get(k)
        show = v if (v and v != "-") else "—"
        cls = "cc" if k == "chief_complaint" else ""
        slip_rows += f"<tr><td class='k'>{label}</td><td class='{cls}'>{escape(str(show))}</td></tr>"

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Call {sid}</title><style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:14px;background:#f4f5f7;color:#222;padding:18px}}
a{{color:#1a6db5;text-decoration:none}}
h1{{font-size:18px;margin-bottom:2px}}
.sub{{color:#777;font-size:12px;margin-bottom:14px}}
.hint{{color:#999;font-size:11px;margin-top:6px}}
.wrap{{display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap}}
.col{{background:#fff;border-radius:10px;box-shadow:0 1px 4px rgba(0,0,0,.08);padding:14px}}
.left{{flex:2;min-width:380px}}.right{{flex:1;min-width:280px}}
.cards{{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}}
.card{{background:#fff;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.07);padding:8px 12px;min-width:96px}}
.cv{{font-size:17px;font-weight:700;color:#1a6db5}}.cl{{font-size:10px;color:#888;text-transform:uppercase;letter-spacing:.4px}}
#transcript{{display:flex;flex-direction:column;gap:6px;margin-top:10px}}
.turn{{max-width:88%;padding:6px 10px;border-radius:10px;line-height:1.4;white-space:pre-wrap;word-wrap:break-word;cursor:pointer}}
.turn.user{{align-self:flex-end;background:#dcefff}}
.turn.bot{{align-self:flex-start;background:#e7e7ee}}
.turn:hover{{filter:brightness(.97)}}
.ts{{font-size:10px;color:#888;margin-right:4px}}
.badge{{font-size:10px;color:#c0392b;margin-top:3px}}
label{{display:block;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.5px;color:#666;margin-bottom:6px}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
td{{padding:5px 8px;border-bottom:1px solid #f0f0f0;vertical-align:top}}
td.k{{color:#777;width:120px;font-size:12px}}
td.cc{{font-weight:700;color:#1a6db5}}
</style></head><body>
<div class="sub"><a href="/playground">&larr; saved calls</a> · <a href="/calls">Telephone history</a></div>
<h1>{name} &middot; {phone}</h1>
<div class="sub">{sid} &middot; status: {status}</div>
<div class="cards">{cards_html}</div>
<div class="wrap">
  <div class="col left">
    {audio_html}
    <label style="margin-top:12px">Transcript</label>
    <div id="transcript">{turns_html}</div>
  </div>
  <div class="col right">
    <label>Doctor's slip</label>
    <table>{slip_rows}</table>
  </div>
</div>
<script>
function seek(t){{var p=document.getElementById('player');if(p){{p.currentTime=t;p.play();}}}}
</script>
</body></html>"""


async def _finalize(agent):
    # On any close that wasn't a clean finish, still produce a usable slip.
    agent._closed = True
    agent._interrupt = True
    await agent._close_stream()   # idempotent; finish() already closed it on clean ends
    s = agent.session
    if s.get("local_call_number"):
        await _finalize_registered_phone(agent)
        return
    if s.get("status") != "complete":
        s["call_end"] = datetime.now().isoformat(timespec="seconds")
        try:
            await agent.finalize_slip()   # post-call extraction (idempotent)
        except Exception as e:
            print(f"[{agent.session_id}] finalize extract error: {e}")
        if s.get("chief_complaint") and s.get("chief_complaint") != "-":
            s["status"] = "partial"
            session_manager.save_session(s)
            pdf_slip.generate(s)
            print(f"[{agent.session_id}] partial PDF generated")
        else:
            s["status"] = "dropped"
            session_manager.save_session(s)
    if agent.recorder:
        agent.recorder.finalize(s)   # idempotent; now the slip fields are present
    print(f"[{agent.session_id}] ws closed (status={s.get('status')})")


async def _finalize_registered_phone(agent):
    s = agent.session
    record = local_calls.get(s["local_call_number"])
    status = "save_failed"
    try:
        local_calls.set_status(record["number"], "finalizing")
        if s.get("status") != "complete":
            s["call_end"] = s.get("call_end") or datetime.now().isoformat(timespec="seconds")
            await agent.finalize_slip()
            s["status"] = ("complete" if getattr(agent, "_ended", False) else
                           "partial" if s.get("chief_complaint") not in (None, "", "-") else "dropped")
        status = "summary_failed" if getattr(agent, "_extraction_failed", False) else s["status"]
        s["status"] = status
        session_manager.save_session(s)
        if status in {"complete", "partial"}:
            try:
                local_calls.save_pdf(record, s, update_status=False)
            except Exception as exc:
                status = "pdf_failed"
                print(f"[phone] PDF save failed: {type(exc).__name__}")
    except Exception as exc:
        status = "save_failed"
        print(f"[phone] call save failed: {type(exc).__name__}")
    finally:
        # Preserve transcript/audio even if extraction or PDF generation fails.
        try:
            if agent.recorder:
                agent.recorder.finalize(s)
        except Exception as exc:
            status = "recording_failed"
            print(f"[phone] recording save failed: {type(exc).__name__}")
        local_calls.set_status(record["number"], status)


@app.get("/calls/{session_id}/audio")
async def call_audio_download(session_id: str):
    sid = os.path.basename(session_id)
    path = os.path.join(recorder.RECORDINGS_DIR, f"{sid}.wav")
    if not os.path.isfile(path):
        return Response(status_code=404)
    filename = sid.removeprefix("phone_") + ".wav"
    return FileResponse(path, media_type="audio/wav", filename=filename,
                        headers={"Cache-Control": "no-store"})
