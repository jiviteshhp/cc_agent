# FastAPI app: /answer webhook (Stream XML) + /stream WebSocket.
# Run from the project root:  uvicorn main:app --host 0.0.0.0 --port 8001

import asyncio
import base64
import json
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime
from urllib.parse import quote

from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import FileResponse, HTMLResponse, Response

load_dotenv()

import pdf_slip
import session_manager
import llm
import playground
import recorder
from agent import ConversationAgent


@asynccontextmanager
async def lifespan(app):
    os.makedirs("sessions", exist_ok=True)
    os.makedirs("pdfs", exist_ok=True)
    os.makedirs("recordings", exist_ok=True)
    try:
        # Nothing to pre-synthesize anymore: Gemini generates every line live, so
        # there are no fixed clips to cache. Just warm the LLM connection so the
        # first real turn isn't a cold start.
        await llm.warm()
        print("[warm] llm ready")
    except Exception as e:
        print(f"[warm] error: {e}")
    print("server ready")
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(playground.router)   # /playground tester (isolated from calls)


@app.post("/answer")
async def answer(request: Request):
    form = await request.form()
    caller = form.get("From", "")
    host = os.environ["SERVER_HOST"]
    caller_q = quote(caller, safe="")
    # Vobiz-side noise cancellation. Level 85 is aggressive and eats into the
    # high-frequency fricative band Sarvam needs to tell खुजली (kh-) from सूजन
    # (s-). Exposed so a clinician can A/B it without a code change:
    #   NOISE_CANCELLATION=false        -> off (cleanest test in a quiet room)
    #   NOISE_CANCELLATION_LEVEL=30     -> lowest that still cuts real ward noise
    nc = os.getenv("NOISE_CANCELLATION", "true")
    nc_level = os.getenv("NOISE_CANCELLATION_LEVEL", "40")
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        "    <Stream\n"
        '        bidirectional="true"\n'
        '        keepCallAlive="true"\n'
        f'        noiseCancellation="{nc}"\n'
        f'        noiseCancellationLevel="{nc_level}">\n'
        f"        wss://{host}/stream?phone={caller_q}\n"
        "    </Stream>\n"
        "</Response>"
    )
    return Response(content=xml, media_type="application/xml")


@app.websocket("/stream")
async def stream(websocket: WebSocket):
    await websocket.accept()
    raw_phone = websocket.query_params.get("phone", "")
    phone_digits = re.sub(r"\D", "", raw_phone)[-10:]

    session_data = (session_manager.find_session_by_phone(phone_digits)
                    if phone_digits else None)
    if not session_data:
        session_data = session_manager.new_session(
            "Walk-in", "-", "-", phone_digits or "unknown")
        print(f"auto session {session_data['session_id']} for {phone_digits}")

    agent = ConversationAgent(websocket, session_data)
    agent.recorder = recorder.CallRecorder(agent.session_id)
    print(f"[{agent.session_id}] call connected ({phone_digits})")
    try:
        while True:
            msg = await websocket.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
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
        s = data.get("start", {})
        agent.stream_id = s.get("streamId") or s.get("streamSid") or s.get("callId")
        print(f"[{agent.session_id}] start event, stream_id={agent.stream_id}")
        # Task so the receive loop keeps draining frames during playback.
        asyncio.create_task(agent.start())
    elif event in ("media", "audio"):
        media = data.get("media") or data.get("audio") or {}
        payload = media.get("payload", "")
        if payload:
            await agent.on_audio(base64.b64decode(payload))
    elif event == "stop":
        print(f"[{agent.session_id}] stop event received")
    elif event in ("clearedAudio", "mark", "dtmf"):
        pass   # Vobiz acks / signals we don't act on; not errors
    else:
        print(f"[{agent.session_id}] unknown event '{event}': {str(data)[:200]}")


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
        return f"<td style='color:{c}'>{v}</td>"

    rows = ""
    for s in sessions:
        st = s.get("status", "")
        sc = colors.get(st, "#666")
        phone = re.sub(r"\D", "", s.get("phone") or "")[-10:] or "—"
        ts = (s.get("call_start") or s.get("created_at") or "")[:16].replace("T", " ")
        sid = s.get("session_id", "")
        rows += (f"<tr><td><a href='/calls/{sid}'><b>{phone}</b></a></td><td>{s.get('name','')}</td>"
                 f"<td><span style='color:{sc};font-weight:600'>{st}</span></td>"
                 f"<td style='color:#888;font-size:11px'>{ts}</td>")
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
<h2>CC Agent &mdash; {len(sessions)} call{"s" if len(sessions)!=1 else ""} (auto-refresh 10s)</h2>
<div class="agg">{agg}</div>
<table><tr><th>Phone</th><th>Name</th><th>Status</th><th>Time</th>{head}<th>Session ID</th></tr>
{rows}</table></body></html>"""


SLIP_LABELS = [("Chief complaint", "chief_complaint"), ("Eye", "laterality"),
               ("Duration", "duration"), ("Follow-up", "dynamic_follow_up"),
               ("Prior treatment", "prior_treatment"), ("Comorbidities", "comorbidities"),
               ("Medications", "medications")]


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
    return _render_call_detail(sid, rec, sess)


def _render_call_detail(sid, rec, sess):
    base = rec or sess or {}
    name = base.get("name") or "—"
    phone = re.sub(r"\D", "", base.get("phone") or "")[-10:] or "—"
    status = base.get("status") or "—"

    if rec and rec.get("audio"):
        audio_html = (f"<audio id='player' controls preload='metadata' "
                      f"src='/recordings/{rec['audio']}' style='width:100%'></audio>"
                      f"<div class='hint'>Left = patient · Right = agent · click a turn to jump</div>")
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
        f"<div class='card'><div class='cv'>{v}</div><div class='cl'>{l}</div></div>"
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
        text = (t.get("text") or "").replace("<", "&lt;").replace(">", "&gt;")
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
        slip_rows += f"<tr><td class='k'>{label}</td><td class='{cls}'>{show}</td></tr>"

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
<div class="sub"><a href="/calls">&larr; all calls</a></div>
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
    await agent._close_stream()   # idempotent; finish() already closed it on clean ends
    s = agent.session
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
