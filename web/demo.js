const $ = id => document.getElementById(id);
const fields = [
  ["laterality", "Affected eye"], ["chief_complaint", "Main complaint"],
  ["duration", "Duration"], ["dynamic_follow_up", "Follow-up detail"],
  ["prior_treatment", "Previous treatment"], ["comorbidities", "Medical history"],
  ["medications", "Current medication"],
];
let config, defaults, current = null, mode = "voice", summary = null;
let assistantBubble = null, partialBubble = null, turns = [], interruptionCount = 0;
let speechEndedAt = null;
const labels = {
  idle: ["Ready when you are", "Start a conversation, then allow your microphone."],
  connecting: ["Getting ready…", "Connecting your microphone and assistant."],
  listening: ["I'm listening", "Take your time. You can speak naturally in Hindi."],
  thinking: ["One moment…", "Your assistant is preparing a reply."],
  speaking: ["Your assistant is speaking", "You can interrupt at any time. Just start talking."],
  finishing: ["Preparing your summary…", "Gathering the information you shared."],
  complete: ["Thank you for sharing", "Your conversation is complete. Review the intake summary."],
  error: ["Let's try that again", "Check the message above, then start a new conversation."],
};
function status(state, hint) {
  $("stage").dataset.state = state;
  $("status").textContent = labels[state][0];
  $("status-hint").textContent = hint || labels[state][1];
}
function showError(message) { $("error-text").textContent = message; $("error").hidden = false; }
function controls(active) {
  for (const id of ["start", "voice", "pace", "edit-prompt", "voice-mode", "text-mode"]) $(id).disabled = active;
  $("end").disabled = !active || !current?.ready || current?.ending;
  $("mute").disabled = !active || mode !== "voice" || !current?.ready || current?.ending;
  $("text-input").disabled = !active || !current?.ready || current?.ending;
  $("send-text").disabled = $("text-input").disabled || current?.busy;
}
function renderSlip(data = {}) {
  $("slip").replaceChildren();
  for (const [key, label] of fields) {
    const item = document.createElement("div"); item.className = "field";
    const dt = document.createElement("dt"); dt.textContent = label;
    const dd = document.createElement("dd");
    const value = data[key]; dd.textContent = value && value !== "-" ? value : (summary ? "Not provided" : "—");
    if (!value || value === "-") dd.className = "pending";
    item.append(dt, dd); $("slip").append(item);
  }
}
function bubble(role, text = "", partial = false) {
  $("empty-transcript")?.remove();
  const wrapper = document.createElement("div"); wrapper.className = `message ${role}${partial ? " partial" : ""}`;
  const who = document.createElement("div"); who.className = "who";
  who.textContent = role === "user" ? (partial ? "YOU · LISTENING" : "YOU") : "ASSISTANT";
  const words = document.createElement("div"); words.className = "words"; words.textContent = text;
  wrapper.append(who, words); $("transcript").append(wrapper); scrollTranscript();
  return {wrapper, who, words};
}
function scrollTranscript() { $("transcript").scrollTop = $("transcript").scrollHeight; }
function clearPartial() { partialBubble?.wrapper.remove(); partialBubble = null; }
function clearConversation() {
  turns = []; summary = null; assistantBubble = null; clearPartial();
  $("transcript").replaceChildren(); renderSlip();
  $("slip-status").textContent = "Prepared after the conversation, from what the patient shared.";
  $("summary-badge").textContent = "Awaiting conversation"; $("download").disabled = true;
  $("response-time").textContent = "—"; $("llm-time").textContent = "—";
  interruptionCount = 0; $("interruptions").textContent = "0"; speechEndedAt = null;
  $("timer").textContent = "00:00"; $("live-label").textContent = "TRANSCRIPT";
}
async function refreshConfig() {
  const response = await fetch("/playground/config", {cache: "no-store"});
  if (!response.ok) throw new Error("Could not read local setup. Is the server running?");
  config = await response.json();
  $("stt-model").textContent = config.stt; $("tts-model").textContent = config.tts;
  $("llm-model").textContent = config.llm;
  $("setup").hidden = config.missing.length === 0;
  $("setup-text").textContent = `Add ${config.missing.join(" and ")} to .env, then click Check again.`;
  return config;
}
function flushAudio(s) {
  for (const source of s.sources) { try { source.stop(); } catch {} source.disconnect(); }
  s.sources.clear(); s.nextTime = 0;
}
function stopMic(s) {
  s.mic?.getTracks().forEach(track => track.stop());
  s.input?.disconnect(); s.capture?.disconnect(); s.zero?.disconnect();
  if (s.capture) s.capture.port.onmessage = null;
}
function release(s, finalState = "idle") {
  if (s.disposed) return;
  s.disposed = true;
  clearTimeout(s.startTimeout); clearTimeout(s.endTimeout); clearInterval(s.clock);
  stopMic(s); flushAudio(s);
  if (s.ws?.readyState < WebSocket.CLOSING) s.ws.close();
  s.ctx?.close().catch(() => {});
  if (current === s) {
    current = null; controls(false); status(finalState);
    $("mute").textContent = "Mute mic"; $("mute").setAttribute("aria-pressed", "false");
    $("live-label").textContent = finalState === "complete" ? "COMPLETE" : "TRANSCRIPT";
  }
}
function failed(s, message) {
  if (current !== s || s.disposed) return;
  showError(message); release(s, "error");
}
function play(s, msg) {
  if (!s.ctx || s.disposed || current !== s) return;
  if (msg.sample_rate !== 24000) { failed(s, "Unexpected speech audio format. Please restart the local server."); return; }
  const raw = atob(msg.pcm);
  if (raw.length % 2) { failed(s, "Incomplete speech audio. Please retry."); return; }
  const bytes = Uint8Array.from(raw, char => char.charCodeAt(0)); const view = new DataView(bytes.buffer);
  const buffer = s.ctx.createBuffer(1, bytes.length / 2, msg.sample_rate);
  const samples = buffer.getChannelData(0);
  for (let i = 0; i < samples.length; i++) samples[i] = view.getInt16(i * 2, true) / 32768;
  const source = s.ctx.createBufferSource(); source.buffer = buffer; source.connect(s.analyser);
  // A short initial margin absorbs network/main-thread jitter. Each subsequent
  // chunk uses the same continuous audio clock; gaps never accumulate by rounding.
  const when = Math.max(s.ctx.currentTime + (s.sources.size ? 0 : .06), s.nextTime);
  s.nextTime = when + buffer.duration; s.sources.add(source);
  source.onended = () => {
    s.sources.delete(source); source.disconnect();
    if (s.completed && !s.sources.size) release(s, "complete");
  };
  source.start(when);
  if (!s.playedTurns.has(msg.turn)) {
    s.playedTurns.add(msg.turn);
    if (speechEndedAt !== null) {
      const delay = performance.now() - speechEndedAt + (when - s.ctx.currentTime) * 1000;
      $("response-time").textContent = `${(delay / 1000).toFixed(2)} s`;
      speechEndedAt = null;
    }
  }
}
function onMessage(s, msg) {
  if (current !== s || s.disposed) return;
  switch (msg.type) {
    case "ready":
      s.ready = true; clearTimeout(s.startTimeout); controls(true);
      $("live-label").textContent = "LIVE SESSION";
      if (mode === "text") $("text-input").focus();
      break;
    case "audio": play(s, msg); break;
    case "clear": flushAudio(s); break;
    case "interrupt":
      if (!s.interruptedTurns.has(msg.data.turn)) {
        s.interruptedTurns.add(msg.data.turn);
        $("interruptions").textContent = String(++interruptionCount);
      }
      break;
    case "status": if (!s.ending) status(msg.data); break;
    case "speech_start": speechEndedAt = null; if (!s.ending) status("listening"); break;
    case "speech_end": speechEndedAt = performance.now(); break;
    case "partial":
      if (!partialBubble) partialBubble = bubble("user", "", true);
      partialBubble.words.textContent = msg.data; scrollTranscript(); break;
    case "final_fragment":
      if (!partialBubble) partialBubble = bubble("user", "", true);
      s.fragments.push(msg.data); partialBubble.words.textContent = s.fragments.join(" ");
      scrollTranscript(); break;
    case "user":
      clearPartial(); s.fragments = []; bubble("user", msg.data); turns.push({role: "user", text: msg.data}); break;
    case "bot":
      bubble("assistant", msg.data); turns.push({role: "assistant", text: msg.data}); break;
    case "bot_start":
      assistantBubble = bubble("assistant"); s.busy = true; controls(true); break;
    case "bot_delta":
      if (!assistantBubble) assistantBubble = bubble("assistant");
      assistantBubble.words.textContent += msg.data; scrollTranscript(); break;
    case "bot_end": {
      if (assistantBubble) {
        assistantBubble.words.textContent = msg.data.text;
        if (!msg.data.text) assistantBubble.wrapper.remove();
        else if (msg.data.interrupted || msg.data.failed) {
          const tag = document.createElement("span"); tag.className = "tag";
          tag.textContent = msg.data.interrupted ? "INTERRUPTED · NOT FULLY HEARD" : "RESPONSE FAILED";
          assistantBubble.who.append(tag);
        }
      }
      if (msg.data.text) turns.push({role: "assistant", ...msg.data});
      assistantBubble = null; s.busy = false; controls(true); break;
    }
    case "metric":
      if (msg.data.llm_first_text_ms !== undefined) $("llm-time").textContent = `${msg.data.llm_first_text_ms} ms`;
      break;
    case "slip_status": $("slip-status").textContent = msg.data; break;
    case "slip":
      summary = msg.data; renderSlip(summary); $("slip-status").textContent = "A draft of the information shared. Ready for your review.";
      $("summary-badge").textContent = "Ready for review"; $("download").disabled = false; break;
    case "error": showError(msg.data); break;
    case "done":
      s.completed = true; s.ready = false; stopMic(s); controls(true); clearPartial();
      if (!s.sources.size) release(s, "complete"); break;
  }
}
async function start() {
  if (current) return;
  const s = {sources: new Set(), nextTime: 0, fragments: [], playedTurns: new Set(), interruptedTurns: new Set(), started: Date.now(), ready: false, busy: false, disposed: false, muted: false, level: 0};
  current = s; $("error").hidden = true; clearConversation(); status("connecting"); controls(true);
  try {
    // Create/resume in the click gesture, before fetch or permission awaits.
    if (mode === "voice") {
      if (!window.AudioContext || !navigator.mediaDevices?.getUserMedia) throw new Error("Use Chrome or Edge on localhost to enable microphone audio.");
      s.ctx = new AudioContext({latencyHint: "interactive"}); await s.ctx.resume();
    }
    await refreshConfig(); if (current !== s) return;
    if (!(mode === "voice" ? config.voice_ready : config.text_ready)) throw new Error("Add the missing API keys to .env, then click Check again.");
    if (!$("prompt").value.trim() || !$("greeting").value.trim()) throw new Error("Enter a conversation prompt and opening message first.");
    if (mode === "voice") {
      const mic = await navigator.mediaDevices.getUserMedia({audio: {channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true}, video: false});
      if (current !== s) { mic.getTracks().forEach(track => track.stop()); return; }
      s.mic = mic;
      await s.ctx.audioWorklet.addModule("/playground/assets/capture-worklet.js");
      if (current !== s) return;
      s.analyser = s.ctx.createAnalyser(); s.analyser.fftSize = 256; s.analyser.connect(s.ctx.destination);
      s.waveform = new Float32Array(s.analyser.fftSize);
      s.input = s.ctx.createMediaStreamSource(mic);
      s.capture = new AudioWorkletNode(s.ctx, "pcm-capture", {numberOfInputs: 1, numberOfOutputs: 1, channelCount: 1});
      s.zero = s.ctx.createGain(); s.zero.gain.value = 0;
      s.input.connect(s.capture); s.capture.connect(s.zero); s.zero.connect(s.ctx.destination);
      s.capture.port.onmessage = ({data}) => {
        s.level = s.muted ? 0 : data.level;
        if (!s.ready || s.disposed || s.ws?.readyState !== WebSocket.OPEN) return;
        if (s.ws.bufferedAmount > 32000) { failed(s, "Audio connection is falling behind. Please restart the conversation."); return; }
        s.ws.send(data.pcm);
      };
    }
    if (current !== s) return;
    const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/playground/stream`); s.ws = ws;
    s.startTimeout = setTimeout(() => failed(s, "The assistant could not connect. Check API access and your internet connection."), 15000);
    ws.onopen = () => {
      if (current !== s) { ws.close(); return; }
      ws.send(JSON.stringify({event: "start", mode, prompt: $("prompt").value, greeting: $("greeting").value, speaker: $("voice").value, pace: Number($("pace").value)}));
    };
    ws.onmessage = event => {
      try { onMessage(s, JSON.parse(event.data)); }
      catch { failed(s, "Could not read the audio stream. Please restart the conversation."); }
    };
    ws.onerror = () => failed(s, "Connection failed. Check that the local server is still running.");
    ws.onclose = () => {
      if (current !== s || s.disposed || s.completed) return;
      const message = $("error").hidden ? "The session disconnected. Start again to reconnect." : $("error-text").textContent;
      failed(s, message);
    };
    s.clock = setInterval(() => {
      const elapsed = Math.floor((Date.now() - s.started) / 1000);
      $("timer").textContent = `${String(Math.floor(elapsed / 60)).padStart(2,"0")}:${String(elapsed % 60).padStart(2,"0")}`;
    }, 1000);
  } catch (error) {
    const message = error.name === "NotAllowedError" ? "Microphone access was denied. Allow the microphone for localhost, then retry."
      : error.name === "NotFoundError" ? "No microphone found. Connect a microphone, or try Text mode." : error.message;
    failed(s, message);
  }
}
function setMode(next) {
  if (current) return;
  mode = next;
  for (const name of ["voice", "text"]) {
    $(`${name}-mode`).classList.toggle("selected", name === mode);
    $(`${name}-mode`).setAttribute("aria-pressed", String(name === mode));
  }
  $("text-form").hidden = mode !== "text";
  $("mute").hidden = mode !== "voice";
  $("start").textContent = mode === "voice" ? "● Start conversation" : "Start text session";
  status("idle", mode === "text" ? "Start a text session to test the same intake prompt." : undefined);
}
$("start").onclick = start;
$("end").onclick = () => {
  const s = current; if (!s?.ready || s.ending) return;
  s.ending = true; s.muted = true; s.mic?.getAudioTracks().forEach(track => { track.enabled = false; });
  status("finishing"); controls(true); s.ws.send(JSON.stringify({event: "end"}));
  s.endTimeout = setTimeout(() => failed(s, "Summary generation timed out. The conversation remains visible."), 40000);
};
$("mute").onclick = () => {
  const s = current; if (!s?.ready) return;
  s.muted = !s.muted; s.mic.getAudioTracks().forEach(track => { track.enabled = !s.muted; });
  $("mute").textContent = s.muted ? "Unmute mic" : "Mute mic";
  $("mute").setAttribute("aria-pressed", String(s.muted));
};
$("reset").onclick = () => { if (current) release(current); clearConversation(); status("idle"); $("error").hidden = true; };
$("voice-mode").onclick = () => setMode("voice"); $("text-mode").onclick = () => setMode("text");
$("dismiss-error").onclick = () => { $("error").hidden = true; };
$("refresh-config").onclick = () => refreshConfig().catch(error => showError(error.message));
$("text-form").onsubmit = event => {
  event.preventDefault(); const s = current; const text = $("text-input").value.trim();
  if (!s?.ready || s.busy || s.ending || !text) return;
  s.busy = true; controls(true); s.ws.send(JSON.stringify({event: "text", text})); $("text-input").value = "";
};
$("edit-prompt").onclick = () => $("prompt-dialog").showModal();
$("use-prompt").onclick = () => {
  if (!$("prompt").value.trim() || !$("greeting").value.trim()) { $("save-note").textContent = "Both fields need text."; return; }
  $("prompt-note").textContent = "Ready for your next conversation"; $("prompt-dialog").close();
};
$("default-prompt").onclick = () => {
  $("prompt").value = defaults.conversation; $("greeting").value = config.greeting;
  $("save-note").textContent = "Original prompt restored in this editor.";
};
$("save-prompt").onclick = async () => {
  try {
    const response = await fetch("/playground/prompts", {method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({conversation: $("prompt").value, save: true})});
    if (!response.ok) throw new Error("Could not save. Check the prompt length and local server.");
    $("save-note").textContent = "Conversation prompt saved locally. Opening message is session-only.";
  } catch (error) { $("save-note").textContent = error.message; }
};
$("download").onclick = () => {
  if (!summary) return;
  const body = ["OPHTHALMOLOGY INTAKE — LOCAL DEMO", "Draft for review", "", ...fields.map(([key,label]) => `${label}: ${summary[key] === "-" ? "Not provided" : summary[key]}`), "", "CONVERSATION", ...turns.map(turn => `${turn.role === "user" ? "Patient" : "Assistant"}: ${turn.text}${turn.interrupted ? " [interrupted]" : ""}`)].join("\n");
  const url = URL.createObjectURL(new Blob([body], {type: "text/plain;charset=utf-8"}));
  const link = document.createElement("a"); link.href = url; link.download = "optha-demo-intake.txt"; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
const bars = [...document.querySelectorAll(".levels i")];
function animate() {
  const s = current; let level = s?.level || 0;
  if (s?.analyser && !s.disposed) {
    s.analyser.getFloatTimeDomainData(s.waveform);
    let energy = 0; for (const sample of s.waveform) energy += sample * sample;
    level = Math.max(level, Math.sqrt(energy / s.waveform.length));
  }
  level = Math.min(1, level * 5);
  $("stage").style.setProperty("--level", level.toFixed(3));
  bars.forEach((bar, index) => { bar.style.height = `${3 + level * 20 * (.25 + .75 * Math.sin((index + 1) * .7) ** 2)}px`; });
  requestAnimationFrame(animate);
}
window.addEventListener("pagehide", () => { if (current) release(current); });
async function initialize() {
  renderSlip(); controls(false); $("start").disabled = true;
  try {
    const [_, response] = await Promise.all([refreshConfig(), fetch("/playground/prompts", {cache:"no-store"})]);
    if (!response.ok) throw new Error("Could not load the intake prompt.");
    const data = await response.json(); defaults = data.defaults;
    $("prompt").value = data.conversation; $("greeting").value = config.greeting;
    $("prompt-note").textContent = "Included intake prompt · edit to customize";
    $("start").disabled = false;
  } catch (error) { showError(error.message); }
  animate();
}
initialize();
