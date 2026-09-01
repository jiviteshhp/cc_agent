# Prompt playground: a self-serve web page (mic + text) for a clinician to test
# the agent and iterate its prompts from their own laptop, reachable through the
# existing ngrok tunnel. Isolated from the phone path:
#   - reuses ConversationAgent, only swapping the Vobiz transport for a browser one,
#   - in-memory only: no sessions/*.json, no PDF, never shows on /calls,
#   - prompt edits come from prompt_store (the phone path keeps its committed
#     defaults in prompts.py).

import asyncio
import base64
import json

from fastapi import APIRouter, Request, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse

import prompt_store
from agent import ConversationAgent

router = APIRouter()


def _new_pg_session(session_id):
    return {"session_id": session_id, "status": "idle"}


class BrowserAgent(ConversationAgent):
    # Same brain (single Gemini prompt) as a phone call, but audio/events go to
    # the browser and nothing is written to disk. The prompt comes from
    # prompt_store; the base start()/handle_text() drive the flow via self._voice.
    def __init__(self, websocket, session, system_prompt):
        super().__init__(websocket, session)
        self.system_prompt = system_prompt
        self._persist = False        # no session JSON, no PDF
        self.mode = "voice"

    async def _send_audio(self, pcm):
        await self._send({"type": "audio", "pcm": base64.b64encode(pcm).decode("ascii")})

    async def _clear_audio(self):
        await self._send({"type": "clear"})

    async def _emit(self, kind, payload):
        try:
            await self._send({"type": kind, "data": payload})
        except Exception:
            pass


async def _on_text(agent, raw):
    try:
        data = json.loads(raw)
    except ValueError:
        return
    event = data.get("event")
    if event == "start":
        agent.mode = data.get("mode", "voice")
        agent._voice = (agent.mode == "voice")
        asyncio.create_task(agent.start())
    elif event == "text":
        await agent.handle_text(data.get("text", ""))
    elif event == "extract":
        try:
            await agent.finalize_slip(force=True)
        except Exception as e:
            await agent._emit("bot", f"[extract error: {e}]")
    elif event == "stop":
        agent._interrupt = True


@router.websocket("/playground/stream")
async def playground_stream(websocket: WebSocket):
    await websocket.accept()
    pr = prompt_store.get()
    agent = BrowserAgent(websocket, _new_pg_session("PLAYGROUND"),
                         pr["conversation"])
    print("[playground] connected")
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
        print(f"[playground] ws ended: {e}")
    finally:
        await agent._close_stream()
        print("[playground] disconnected")


@router.get("/playground/prompts")
async def get_prompts():
    return JSONResponse({**prompt_store.get(), "defaults": prompt_store.defaults()})


@router.post("/playground/prompts")
async def set_prompts(request: Request):
    body = await request.json()
    prompt_store.update(body.get("conversation", ""))
    saved = bool(body.get("save"))
    if saved:
        prompt_store.save()
    return JSONResponse({"ok": True, "saved": saved})


@router.post("/playground/prompts/revert")
async def revert_prompts():
    prompt_store.revert()
    return JSONResponse({"ok": True, **prompt_store.get()})


@router.get("/playground", response_class=HTMLResponse)
async def playground_page():
    return PAGE


PAGE = r"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Eye-OPD Agent — Prompt Playground</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:14px;background:#f4f5f7;color:#222;padding:18px}
h1{font-size:18px;margin-bottom:4px}
.sub{color:#777;font-size:12px;margin-bottom:14px}
.wrap{display:flex;gap:16px;align-items:flex-start}
.col{background:#fff;border-radius:10px;box-shadow:0 1px 4px rgba(0,0,0,.08);padding:14px}
.left{flex:1;min-width:360px;max-height:82vh;overflow-y:auto}
.right{flex:1;min-width:340px;display:flex;flex-direction:column;gap:12px}
label{display:block;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.5px;color:#666;margin:10px 0 4px}
textarea,input[type=text],input:not([type]){width:100%;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;line-height:1.45;border:1px solid #ddd;border-radius:6px;padding:8px;resize:vertical}
#conv{height:520px}
button{font-size:13px;border:0;border-radius:6px;padding:7px 13px;cursor:pointer;background:#eef;color:#225;font-weight:600}
button:hover{filter:brightness(.96)}
button.primary{background:#1a6db5;color:#fff}
button.warn{background:#fdeaea;color:#c0392b}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:10px}
.tag{font-size:12px;color:#2a7a4b;margin-left:6px}
.tabs{display:flex;gap:6px;margin-bottom:8px}
.tab{background:#eee;color:#555}
.tab.active{background:#1a6db5;color:#fff}
#status{font-size:12px;font-weight:600;color:#666}
#transcript{height:300px;overflow-y:auto;border:1px solid #eee;border-radius:6px;padding:10px;background:#fafafa;display:flex;flex-direction:column;gap:6px}
.msg{max-width:85%;padding:6px 10px;border-radius:10px;line-height:1.4;white-space:pre-wrap;word-wrap:break-word}
.msg.user{align-self:flex-end;background:#dcefff}
.msg.bot{align-self:flex-start;background:#e7e7ee}
.msg.sys{align-self:center;background:transparent;color:#999;font-size:12px}
#textbar{display:flex;gap:8px;margin-top:8px}
#textbar input{flex:1;padding:8px;font-family:inherit;font-size:14px}
table{border-collapse:collapse;width:100%;font-size:13px}
td{padding:5px 8px;border-bottom:1px solid #f0f0f0;vertical-align:top}
td.k{color:#777;width:130px;font-size:12px}
td.cc{font-weight:700;color:#1a6db5}
.hint{font-size:11px;color:#999;margin-top:6px}
</style></head><body>
<h1>Eye-OPD Agent — Prompt Playground</h1>
<div class="sub">Edit the prompts on the left, then talk or type on the right. The doctor's slip updates so you can judge chief-complaint accuracy. Tip: use headphones to avoid echo. Text mode is free (no voice APIs).</div>

<div class="wrap">
  <div class="col left">
    <label>Conversation prompt (drives the whole call — Gemini Flash)</label>
    <textarea id="conv" spellcheck="false"></textarea>
    <div class="row">
      <button class="primary" onclick="applyV2(false)">Apply</button>
      <button onclick="applyV2(true)">Save</button>
      <button class="warn" onclick="revertV2()">Revert to default</button>
      <span id="pstatus2" class="tag"></span>
    </div>
    <div class="hint">Apply = use on the next conversation (in memory). Save = keep across restarts. After Apply, click <b>New conversation</b> then start again to test it. Slip fields are extracted after the call ends (or click <b>Extract slip</b>).</div>
  </div>

  <div class="right">
    <div class="col">
      <div class="tabs">
        <button class="tab active" id="tabVoice" onclick="setMode('voice')">🎤 Voice</button>
        <button class="tab" id="tabText" onclick="setMode('text')">⌨️ Text</button>
        <span style="flex:1"></span>
        <span id="status">ready</span>
      </div>

      <div id="voiceCtl" class="row">
        <button class="primary" id="btnStart" onclick="startVoice()">● Start talking</button>
        <button id="btnStop" onclick="stopVoice()" disabled>■ Pause mic</button>
      </div>

      <div id="transcript"></div>

      <div id="textbar" style="display:none">
        <input type="text" id="textIn" placeholder="Type a patient reply in Hindi…" onkeydown="if(event.key==='Enter')sendText()">
        <button class="primary" onclick="sendText()">Send</button>
      </div>

      <div class="row">
        <button id="btnExtract" onclick="doExtract()">Extract slip</button>
        <button onclick="newConvo()">New conversation</button>
      </div>
    </div>

    <div class="col">
      <label>Doctor's slip</label>
      <table id="slip"><tr><td class="k">—</td><td>start a conversation, then talk/type</td></tr></table>
    </div>
  </div>
</div>

<script>
const FIELDS=[["chief_complaint","Chief complaint",true],["laterality","Eye"],["duration","Duration"],
["dynamic_follow_up","Follow-up"],["prior_treatment","Prior treatment"],["comorbidities","Comorbidities"],
["medications","Medications"]];
const convTA=document.getElementById('conv');
const statusEl=document.getElementById('status');
const transcriptEl=document.getElementById('transcript'), slipEl=document.getElementById('slip');
const textIn=document.getElementById('textIn');
let ws=null, mode='voice';
let audioCtx=null, micStream=null, proc=null, recording=false;
let playCtx=null, nextTime=0, sources=[];

function setStatus(t,c){statusEl.textContent=t;statusEl.style.color=c||'#666';}
function wsUrl(){const p=location.protocol==='https:'?'wss':'ws';return p+'://'+location.host+'/playground/stream';}

function addMsg(who,text){const d=document.createElement('div');d.className='msg '+who;d.textContent=text;
  transcriptEl.appendChild(d);transcriptEl.scrollTop=transcriptEl.scrollHeight;}

function renderSlip(d){
  if(!d){slipEl.innerHTML='<tr><td class="k">—</td><td>start a conversation, then talk/type</td></tr>';return;}
  let h='';for(const f of FIELDS){const v=d[f[0]];const show=(v&&v!=='-')?v:'—';
    h+='<tr><td class="k">'+f[1]+'</td><td class="'+(f[2]?'cc':'')+'">'+show+'</td></tr>';}
  slipEl.innerHTML=h;
}

// ---- audio playback (8kHz PCM from the server) ----
function ensurePlay(){if(!playCtx)playCtx=new (window.AudioContext||window.webkitAudioContext)();if(playCtx.state==='suspended')playCtx.resume();}
function b64ToF32(b64){const bin=atob(b64);const n=bin.length>>1;const f=new Float32Array(n);
  for(let i=0;i<n;i++){let v=bin.charCodeAt(i*2)|(bin.charCodeAt(i*2+1)<<8);if(v>=0x8000)v-=0x10000;f[i]=v/0x8000;}return f;}
function enqueueAudio(b64){ensurePlay();const f=b64ToF32(b64);if(!f.length)return;
  const buf=playCtx.createBuffer(1,f.length,8000);buf.copyToChannel(f,0);
  const s=playCtx.createBufferSource();s.buffer=buf;s.connect(playCtx.destination);
  const now=playCtx.currentTime;if(nextTime<now)nextTime=now;s.start(nextTime);nextTime+=buf.duration;
  sources.push(s);s.onended=()=>{const i=sources.indexOf(s);if(i>=0)sources.splice(i,1);};}
function flushAudio(){sources.forEach(s=>{try{s.stop();}catch(e){}});sources=[];nextTime=0;}

// ---- mic capture -> 8kHz Int16 ----
function downsample(f32,inRate){const out=8000;if(inRate===out){const o=new Int16Array(f32.length);
    for(let i=0;i<f32.length;i++){let v=Math.max(-1,Math.min(1,f32[i]));o[i]=v<0?v*0x8000:v*0x7FFF;}return o;}
  const ratio=inRate/out,len=Math.floor(f32.length/ratio),o=new Int16Array(len);
  for(let i=0;i<len;i++){const idx=i*ratio,lo=Math.floor(idx),fr=idx-lo;
    let s=(f32[lo]||0)*(1-fr)+(f32[lo+1]||0)*fr;s=Math.max(-1,Math.min(1,s));o[i]=s<0?s*0x8000:s*0x7FFF;}
  return o;}

function onMsg(ev){let m;try{m=JSON.parse(ev.data);}catch(e){return;}
  if(m.type==='audio')enqueueAudio(m.pcm);
  else if(m.type==='clear')flushAudio();
  else if(m.type==='user')addMsg('user',m.data);
  else if(m.type==='bot')addMsg('bot',m.data);
  else if(m.type==='slip')renderSlip(m.data);
  else if(m.type==='done')addMsg('sys','— conversation ended —');}

function openWs(m){return new Promise((res,rej)=>{
  if(ws&&ws.readyState===1){res();return;}
  ws=new WebSocket(wsUrl());ws.binaryType='arraybuffer';
  ws.onopen=()=>{setStatus('connected','#2a7a4b');ws.send(JSON.stringify({event:'start',mode:m}));res();};
  ws.onclose=()=>{setStatus('disconnected','#c0392b');recording=false;
    document.getElementById('btnStart').disabled=false;document.getElementById('btnStop').disabled=true;};
  ws.onerror=(e)=>{setStatus('connection error','#c0392b');rej(e);};
  ws.onmessage=onMsg;});}

async function startVoice(){
  try{
    if(!audioCtx)audioCtx=new (window.AudioContext||window.webkitAudioContext)();
    if(audioCtx.state==='suspended')await audioCtx.resume();
    ensurePlay();
    if(!micStream)micStream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
    await openWs('voice');
    if(!proc){
      const src=audioCtx.createMediaStreamSource(micStream);
      proc=audioCtx.createScriptProcessor(4096,1,1);
      proc.onaudioprocess=(e)=>{if(!recording||!ws||ws.readyState!==1)return;
        ws.send(downsample(e.inputBuffer.getChannelData(0),audioCtx.sampleRate).buffer);};
      src.connect(proc);const g=audioCtx.createGain();g.gain.value=0;proc.connect(g);g.connect(audioCtx.destination);
    }
    recording=true;setStatus('listening… speak now','#1a6db5');
    document.getElementById('btnStart').disabled=true;document.getElementById('btnStop').disabled=false;
  }catch(e){setStatus('mic error: '+e.message,'#c0392b');}
}
function stopVoice(){recording=false;setStatus('mic paused','#d68910');
  document.getElementById('btnStart').disabled=false;document.getElementById('btnStop').disabled=true;}

async function sendText(){const t=textIn.value.trim();if(!t)return;await openWs('text');
  ws.send(JSON.stringify({event:'text',text:t}));textIn.value='';}

function doExtract(){if(ws&&ws.readyState===1){ws.send(JSON.stringify({event:'extract'}));setStatus('extracting slip…','#1a6db5');}else{setStatus('start a conversation first','#d68910');}}

function newConvo(){recording=false;if(ws){try{ws.close();}catch(e){}ws=null;}flushAudio();
  transcriptEl.innerHTML='';renderSlip(null);setStatus('ready','#666');
  document.getElementById('btnStart').disabled=false;document.getElementById('btnStop').disabled=true;}

function setMode(m){mode=m;
  document.getElementById('tabVoice').classList.toggle('active',m==='voice');
  document.getElementById('tabText').classList.toggle('active',m==='text');
  document.getElementById('voiceCtl').style.display=(m==='voice')?'flex':'none';
  document.getElementById('textbar').style.display=(m==='text')?'flex':'none';}

// ---- prompt editor ----
async function loadV2Prompts(){const r=await fetch('/playground/prompts');const d=await r.json();
  convTA.value=d.conversation;}
async function applyV2(save){
  await fetch('/playground/prompts',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({conversation:convTA.value,save:!!save})});
  const el=document.getElementById('pstatus2');el.textContent=save?'saved ✓':'applied ✓ — New + Start to test';
  setTimeout(()=>el.textContent='',3500);}
async function revertV2(){const r=await fetch('/playground/prompts/revert',{method:'POST'});
  const d=await r.json();convTA.value=d.conversation;
  const el=document.getElementById('pstatus2');el.textContent='reverted ✓';setTimeout(()=>el.textContent='',3500);}

loadV2Prompts();
</script>
</body></html>"""
