const $ = id => document.getElementById(id);
const fields = [
  ["laterality", "Affected eye"], ["chief_complaint", "Main complaint"],
  ["duration", "Duration"], ["dynamic_follow_up", "Follow-up detail"],
  ["prior_treatment", "Previous treatment"], ["comorbidities", "Medical history"],
  ["medications", "Current medication"],
  ["additional_details", "Other patient-reported details"],
  ["uncertainties", "Needs clarification"],
];
let config, defaults, current = null, mode = "voice", summary = null;
let assistantBubble = null, partialBubble = null, turns = [], interruptionCount = 0;
let speechEndedAt = null, savedCall = null, savedFirstMessage = null;
const labels = {
  idle: ["Ready when you are", "Start a conversation, then allow your microphone."],
  connecting: ["Getting ready…", "Connecting your microphone and assistant."],
  listening: ["I'm listening", "Take your time. You can speak naturally in Hindi."],
  thinking: ["One moment…", "Your assistant is preparing a reply."],
  speaking: ["Your assistant is speaking", "To interrupt, say a short phrase or say “रुकिए”."],
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
function showDiagnostic(data) {
  const components = {asr:"ASR · Speech recognition", llm:"LLM · Reply generation", tts:"TTS · Speech synthesis",
    s2s:"Gemini Live · Speech-to-speech",
    playback:"Browser audio", transport:"Connection", microphone:"Microphone", interruption:"Interruption", application:"Application"};
  const categories = {authentication_or_access:"Authentication or access denied", quota_or_rate_limit:"Rate limit or quota",
    credits_exhausted:"Provider credits exhausted", rate_limited:"Provider rate limit reached",
    provider_server:"Provider server error", timeout:"Timed out", connection:"Connection failed",
    invalid_data_or_configuration:"Invalid data or configuration", provider_rejected:"Provider rejected the request",
    provider_or_application:"Cause not supplied", empty_response:"Model returned no usable text",
    playback_error:"Audio could not be played", context_suspended:"Browser audio context suspended",
    buffer_underrun:"Audio buffer ran empty", microphone_denied:"Microphone permission denied",
    capture_failure:"Microphone capture unavailable", recognized_speech:"Recognized speech cancelled the reply",
    manual_stop:"Manually stopped", call_end:"Call ended", stt_failure:"Speech recognition became unavailable",
    native_barge_in:"Gemini detected an interruption", session_ending:"Provider session is ending",
    control:"Playback cancelled"};
  const item = document.createElement("li"), title = document.createElement("strong"), detail = document.createElement("p");
  title.textContent = `${components[data.component] || "Application"} — ${categories[data.category] || "Cause not supplied"}`;
  const parts = [`${data.outcome || "failed"} · stage: ${data.stage || "unknown"}`];
  if (Number.isInteger(data.turn)) parts.push(`turn ${data.turn}`);
  if (Number.isFinite(data.max_gap_ms)) parts.push(`longest gap ${data.max_gap_ms} ms`);
  if (data.validation_fields?.length) parts.push(`fields: ${data.validation_fields.join(", ")}`);
  if (data.validation_types?.length) parts.push(`validation: ${data.validation_types.join(", ")}`);
  if (data.http_status) parts.push(`HTTP ${data.http_status}`);
  if (data.close_code) parts.push(`socket ${data.close_code}`);
  if (data.provider_code) parts.push(data.provider_code);
  if (data.provider_code_state === "missing") parts.push("provider code not supplied");
  if (data.provider_code_state === "unrecognized") parts.push("unrecognized provider code withheld");
  if (data.provider_request_id) parts.push(`provider request ${data.provider_request_id}`);
  if (data.call) parts.push(`reference ${data.call}`);
  detail.textContent = parts.join(" · "); item.append(title, detail);
  $("diagnostic-list").prepend(item);
  while ($("diagnostic-list").children.length > 20) $("diagnostic-list").lastElementChild.remove();
  $("diagnostic-count").textContent = String($("diagnostic-list").children.length);
  $("diagnostic-empty").hidden = true;
  if (data.outcome !== "interrupted") $("diagnostics").open = true;
}
function controls(active) {
  for (const id of ["patient-name", "patient-age", "start", "voice-engine", "voice", "pace", "expressiveness", "barge-in-min-words", "edit-prompt", "edit-asr", "edit-extraction", "prompt", "s2s-prompt", "s2s-first-message", "greeting", "extraction-prompt", "asr-prompt", "asr-keyterms", "save-prompt", "default-prompt", "use-prompt", "voice-mode", "text-mode"]) $(id).disabled = active;
  $("voice-engine").disabled = active || mode === "text";
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
  $("diagnostic-list").replaceChildren(); $("diagnostic-count").textContent = "0";
  $("diagnostic-empty").hidden = false; $("diagnostics").open = false;
  savedCall = null; turns = []; summary = null; assistantBubble = null; clearPartial();
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
  updateEngineUI();
  return config;
}
function selectedEngine() { return mode === "voice" ? $("voice-engine").value : "cascaded"; }
function updateEngineUI() {
  const native = selectedEngine() === "s2s";
  $("cascaded-settings").hidden = native;
  $("s2s-settings").hidden = !native;
  $("edit-asr").hidden = native;
  $("cascaded-prompt-settings").hidden = native;
  $("s2s-prompt-settings").hidden = !native;
  $("cascaded-greeting-settings").hidden = native;
  $("asr-settings").hidden = native;
  $("engine-help").textContent = mode === "text" ? "Text sessions use the cascaded conversation prompt and text model."
    : "Choose before starting a call. Both follow the same intake and save a PDF.";
  if (!config) return;
  $("stt-model").textContent = native ? "Gemini Live audio" : config.stt;
  $("tts-model").textContent = native ? `Gemini · ${config.s2s_voice}` : config.tts;
  $("llm-model").textContent = native ? config.s2s_model : config.llm;
  const missing = native ? config.s2s_missing : mode === "text" ? config.missing.filter(key => key !== "SARVAM_API_KEY") : config.missing;
  $("setup").hidden = missing.length === 0;
  $("setup-text").textContent = `Add ${missing.join(" and ")} to .env, then click Check again.`;
}
function flushAudio(s) {
  for (const source of s.sources) { source.cleared = true; try { source.stop(); } catch {} source.disconnect(); }
  s.sources.clear(); s.nextTime = 0; s.playbackTurn = null;
  s.audioDoneTurns?.clear();
}
function stopMic(s) {
  clearTimeout(s.micTimeout); s.captureAbort?.abort(); s.cancelCapture?.();
  s.mic?.getTracks().forEach(track => track.stop());
  s.input?.disconnect(); s.highpass?.disconnect(); s.capture?.disconnect(); s.zero?.disconnect();
  if (s.capture) {
    s.capture.port.postMessage("destroy"); s.capture.port.onmessage = null;
    s.capture.removeEventListener("processorerror", s.captureError); s.capture.port.close();
  }
}
function release(s, finalState = "idle") {
  if (s.disposed) return;
  s.disposed = true;
  clearTimeout(s.startTimeout); clearTimeout(s.endTimeout); clearInterval(s.clock);
  stopMic(s); flushAudio(s);
  if (s.ws?.readyState < WebSocket.CLOSING) s.ws.close();
  s.ctx?.close().catch(() => {});
  if (current === s) {
    current = null; setTimeout(refreshCalls, 300); controls(false); status(finalState);
    $("mute").textContent = "Mute mic"; $("mute").setAttribute("aria-pressed", "false");
    $("live-label").textContent = finalState === "complete" ? "COMPLETE" : "TRANSCRIPT";
  }
}
function failed(s, message) {
  if (current !== s || s.disposed) return;
  showError(message); release(s, "error");
}
function playbackDiagnostic(s, code, turn, metrics = {}) {
  s.diagnostics ??= new Set();
  const key = `${turn}:${code}`;
  if (s.diagnostics.has(key) || s.diagnostics.size >= 256) return;
  s.diagnostics.add(key);
  if (["playback_error", "context_suspended", "buffer_underrun"].includes(code)) {
    showDiagnostic({component:"playback", stage:"playback", category:code, turn,
      outcome:code === "playback_error" ? "failed" : "warning", ...metrics});
  }
  if (s.ws?.readyState === WebSocket.OPEN) {
    s.ws.send(JSON.stringify({event:"playback_diagnostic", code, turn, ...metrics}));
  }
}
function play(s, msg) {
  try { scheduleAudio(s, msg); }
  catch {
    playbackDiagnostic(s, "playback_error", msg.turn);
    failed(s, "Audio playback failed on this device. Please start a new conversation.");
  }
}
function scheduleAudio(s, msg) {
  if (!s.ctx || s.disposed || current !== s) return;
  if (msg.sample_rate !== 24000) {
    playbackDiagnostic(s, "playback_error", msg.turn);
    failed(s, "Unexpected speech audio format. Please restart the local server."); return;
  }
  const raw = atob(msg.pcm);
  if (raw.length % 2) {
    playbackDiagnostic(s, "playback_error", msg.turn);
    failed(s, "Incomplete speech audio. Please restart the conversation."); return;
  }
  if (s.ctx.state === "suspended") playbackDiagnostic(s, "context_suspended", msg.turn);
  s.playbackStats ??= new Map(); s.audioDoneTurns ??= new Set();
  s.bufferTarget ??= .30;
  const newTurn = s.playbackTurn !== msg.turn;
  if (newTurn) { s.playbackTurn = msg.turn; s.nextTime = 0; }
  const stats = s.playbackStats.get(msg.turn) || {gap_count:0, max_gap_ms:0, total_gap_ms:0,
    max_arrival_gap_ms:0, start_buffer_ms:Math.round(s.bufferTarget * 1000)};
  const now = s.ctx.currentTime;
  if (stats.lastArrival !== undefined) stats.max_arrival_gap_ms = Math.max(stats.max_arrival_gap_ms, Math.round((now - stats.lastArrival)*1000));
  stats.lastArrival = now;
  const gap = s.nextTime > 0 ? Math.max(0, now - s.nextTime) : 0;
  if (gap >= .02) {
    stats.gap_count++; stats.max_gap_ms = Math.max(stats.max_gap_ms, Math.round(gap*1000));
    stats.total_gap_ms += Math.round(gap*1000);
    // Adapt the NEXT turn's startup cushion, never repeatedly add a large pause.
    s.bufferTarget = Math.min(.5, s.bufferTarget + .05);
    playbackDiagnostic(s, "buffer_underrun", msg.turn, playbackMetrics(stats));
  }
  s.playbackStats.set(msg.turn, stats);
  const bytes = Uint8Array.from(raw, char => char.charCodeAt(0)); const view = new DataView(bytes.buffer);
  const buffer = s.ctx.createBuffer(1, bytes.length / 2, msg.sample_rate);
  const samples = buffer.getChannelData(0);
  for (let i = 0; i < samples.length; i++) samples[i] = view.getInt16(i * 2, true) / 32768;
  const source = s.ctx.createBufferSource(); source.buffer = buffer; source.connect(s.analyser);
  // A short initial margin absorbs network/main-thread jitter. Each subsequent
  // chunk uses the same continuous audio clock; gaps never accumulate by rounding.
  const when = s.nextTime > now ? s.nextTime : now + (newTurn ? s.bufferTarget : .02);
  s.nextTime = when + buffer.duration; s.sources.add(source);
  source.onended = () => {
    s.sources.delete(source); source.disconnect();
    if (!source.cleared && !s.disposed) completePlayback(s, msg.turn);
    if (s.completed && !s.sources.size) release(s, "complete");
  };
  source.start(when);
  playbackDiagnostic(s, "audio_scheduled", msg.turn);
  if (!s.playedTurns.has(msg.turn)) {
    s.playedTurns.add(msg.turn);
    if (speechEndedAt !== null) {
      const delay = performance.now() - speechEndedAt + (when - s.ctx.currentTime) * 1000;
      $("response-time").textContent = `${(delay / 1000).toFixed(2)} s`;
      speechEndedAt = null;
    }
  }
}
function playbackMetrics(stats = {}) {
  return Object.fromEntries(["gap_count", "max_gap_ms", "total_gap_ms", "max_arrival_gap_ms", "start_buffer_ms"]
    .map(key => [key, Math.min(120000, Math.max(0, Math.round(stats[key] || 0)))]));
}
function completePlayback(s, turn) {
  if (s.sources.size || !s.audioDoneTurns?.has(turn) || s.playbackTurn !== turn) return;
  const stats = s.playbackStats?.get(turn);
  playbackDiagnostic(s, "audio_ended", turn, playbackMetrics(stats));
  if (stats && !stats.gap_count) s.bufferTarget = Math.max(.30, s.bufferTarget - .025);
  s.audioDoneTurns.delete(turn);
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
    case "audio_end":
      s.audioDoneTurns ??= new Set(); s.audioDoneTurns.add(msg.turn);
      completePlayback(s, msg.turn); break;
    case "clear": flushAudio(s); break;
    case "interrupt":
      if (!s.interruptedTurns.has(msg.data.turn)) {
        s.interruptedTurns.add(msg.data.turn);
        $("interruptions").textContent = String(++interruptionCount);
        showDiagnostic({component:"interruption", category:["recognized_partial", "recognized_final", "recognized_speech"].includes(msg.data.reason) ? "recognized_speech" : (msg.data.reason || "control"),
                        stage:msg.data.reason || "unknown", outcome:"interrupted", turn:msg.data.turn});
      }
      break;
    case "status": if (!s.ending) status(msg.data); break;
    case "speech_start": speechEndedAt = null; if (!s.ending) status("listening"); break;
    case "speech_end": speechEndedAt = performance.now(); break;
    case "partial":
      if (!partialBubble) partialBubble = bubble("user", "", true);
      partialBubble.words.textContent = msg.data; scrollTranscript(); break;
    case "partial_clear":
      if (s.fragments.length && partialBubble) partialBubble.words.textContent = s.fragments.join(" ");
      else clearPartial();
      break;
    case "final_fragment":
      if (!partialBubble) partialBubble = bubble("user", "", true);
      s.fragments.push(msg.data); partialBubble.words.textContent = s.fragments.join(" ");
      scrollTranscript(); break;
    case "user":
      if (partialBubble) {
        partialBubble.words.textContent = msg.data; partialBubble.who.textContent = "YOU";
        partialBubble.wrapper.classList.remove("partial"); partialBubble = null;
      } else bubble("user", msg.data);
      s.fragments = []; turns.push({role: "user", text: msg.data}); break;
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
          tag.textContent = msg.data.interrupted ? "INTERRUPTED · NOT FULLY HEARD"
            : msg.data.failure_stage === "tts" ? "AUDIO FAILED"
            : msg.data.failure_stage === "llm" ? "REPLY INCOMPLETE" : "RESPONSE FAILED";
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
      $("summary-badge").textContent = "Ready for review"; break;
    case "registered_call":
      $("active-person").textContent = `Call ${String(msg.data.number).padStart(3, "0")} · ${msg.data.name} · Age ${msg.data.age}`;
      refreshCalls(); break;
    case "saved_call":
      savedCall = msg.data; $("download").disabled = false;
      $("slip-status").textContent = `Saved locally as ${savedCall.filename}. Ready for review.`;
      $("patient-name").value = ""; $("patient-age").value = "";
      refreshCalls(); break;
    case "error": showError(msg.data); break;
    case "diagnostic": showDiagnostic(msg.data); break;
    case "done":
      s.completed = true; s.ready = false; stopMic(s); controls(true); clearPartial();
      if (!s.sources.size) release(s, "complete"); break;
  }
}
async function start() {
  if (current) return;
  if (!$("patient-form").reportValidity()) return;
  if (selectedEngine() === "cascaded" && !$("barge-in-min-words").reportValidity()) return;
  const engine = selectedEngine();
  const minWords = Number($("barge-in-min-words").value);
  let settings;
  try { settings = editorSettings(); }
  catch (error) { showError(error.message); return; }
  const name = $("patient-name").value.trim(), age = Number($("patient-age").value);
  if (!name) { showError("Enter the person’s name."); return; }
  const s = {sources: new Set(), nextTime: 0, fragments: [], playedTurns: new Set(), interruptedTurns: new Set(), started: Date.now(), ready: false, busy: false, disposed: false, muted: false, level: 0};
  let setupComponent = "playback", setupStage = "audio_context";
  current = s; $("error").hidden = true; clearConversation(); status("connecting"); controls(true);
  try {
    // Create/resume in the click gesture, before fetch or permission awaits.
    if (mode === "voice") {
      if (!window.AudioContext || !navigator.mediaDevices?.getUserMedia) throw new Error("Microphone access needs localhost or trusted HTTPS. On Android, install the local CA certificate and use the HTTPS address.");
      s.ctx = new AudioContext({latencyHint: "interactive", sampleRate: 48000}); await s.ctx.resume();
      if (s.ctx.sampleRate !== 48000) throw new Error("This browser cannot start noise-filtered audio. Try a current browser or Text mode.");
    }
    if (engine === 's2s') {
      setupComponent = 's2s'; setupStage = 'prepare_first_message';
      await prepareOpening(settings.s2s_first_message);
      if (current !== s) return;
    }
    setupComponent = "application"; setupStage = "configuration";
    await refreshConfig(); if (current !== s) return;
    if (!(engine === "s2s" ? config.s2s_ready : mode === "voice" ? config.voice_ready : config.text_ready)) throw new Error("Add the missing API keys to .env, then click Check again.");
    if (mode === "voice") {
      setupComponent = "microphone"; setupStage = "capture";
      // Avoid lifting the room-noise floor during pauses. AEC/noise suppression
      // remain enabled; there is no amplitude gate that clips quiet syllables.
      const mic = await navigator.mediaDevices.getUserMedia({audio: {channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: false}, video: false});
      if (current !== s) { mic.getTracks().forEach(track => track.stop()); return; }
      s.mic = mic;
      s.captureAbort = new AbortController();
      s.micTimeout = setTimeout(() => failed(s, "Microphone noise filtering could not start. Check your connection and retry."), 15000);
      const response = await fetch("/playground/assets/rnnoise.wasm", {signal: s.captureAbort.signal});
      if (!response.ok) throw new Error("Could not load microphone noise filtering. Reload the page and retry.");
      const wasmBinary = await response.arrayBuffer();
      if (current !== s) return;
      await s.ctx.audioWorklet.addModule("/playground/assets/capture-worklet.js");
      if (current !== s) return;
      s.analyser = s.ctx.createAnalyser(); s.analyser.fftSize = 256; s.analyser.connect(s.ctx.destination);
      s.waveform = new Float32Array(s.analyser.fftSize);
      s.input = s.ctx.createMediaStreamSource(mic);
      s.highpass = s.ctx.createBiquadFilter(); s.highpass.type = "highpass";
      s.highpass.frequency.value = 85; s.highpass.Q.value = Math.SQRT1_2;
      s.capture = new AudioWorkletNode(s.ctx, "pcm-capture", {numberOfInputs: 1, numberOfOutputs: 1, channelCount: 1, processorOptions: {wasmBinary}});
      s.zero = s.ctx.createGain(); s.zero.gain.value = 0;
      s.input.connect(s.highpass); s.highpass.connect(s.capture);
      s.capture.connect(s.zero); s.zero.connect(s.ctx.destination);
      await new Promise((resolve, reject) => {
        s.cancelCapture = () => reject(new Error("Microphone setup cancelled"));
        const captureFailed = () => {
          const message = "Microphone noise filtering failed. Please restart the conversation or try another browser.";
          if (current === s && !s.disposed) showDiagnostic({component:"microphone", stage:"noise_filter", category:"capture_failure"});
          reject(new Error(message)); failed(s, message);
        };
        s.captureError = captureFailed;
        s.capture.addEventListener("processorerror", captureFailed, {once: true});
        s.capture.port.onmessage = ({data}) => {
          if (data.type === "ready") { resolve(); return; }
          if (data.type === "error") { captureFailed(); return; }
          s.level = s.muted ? 0 : data.level;
          if (!s.ready || s.disposed || s.ws?.readyState !== WebSocket.OPEN) return;
          if (s.ws.bufferedAmount > 32000) { failed(s, "Audio connection is falling behind. Please restart the conversation."); return; }
          // A muted track can leave a short tail in the denoiser's frame buffer.
          s.ws.send(s.muted ? new ArrayBuffer(data.pcm.byteLength) : data.pcm);
        };
      });
      s.cancelCapture = null; clearTimeout(s.micTimeout);
    }
    if (current !== s) return;
    const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/playground/stream${engine === "s2s" ? "?engine=s2s" : ""}`); s.ws = ws;
    s.startTimeout = setTimeout(() => failed(s, "The assistant could not connect. Check API access and your internet connection."), 15000);
    ws.onopen = () => {
      if (current !== s) { ws.close(); return; }
      ws.send(JSON.stringify({event: "start", name, age, mode, engine, prompt: engine === "s2s" ? settings.s2s_conversation : settings.conversation, extraction: settings.extraction, asr_prompt: settings.asr_prompt, asr_keyterms: settings.asr_keyterms, greeting: engine === "s2s" ? settings.s2s_first_message : $("greeting").value, speaker: $("voice").value, pace: Number($("pace").value), temperature: Number($("expressiveness").value), playback_ack: true, barge_in_min_words: minWords}));
    };
    ws.onmessage = event => {
      try { onMessage(s, JSON.parse(event.data)); }
      catch { failed(s, "Could not read the audio stream. Please restart the conversation."); }
    };
    ws.onerror = () => {
      if (current === s && !s.disposed) showDiagnostic({component:"transport", stage:"websocket", category:"connection"});
      failed(s, "Connection failed. Check that the local server is still running.");
    };
    ws.onclose = event => {
      if (current !== s || s.disposed || s.completed) return;
      showDiagnostic({component:"transport", stage:"websocket_close", category:"connection", close_code:event.code});
      const message = $("error").hidden ? "The session disconnected. Start again to reconnect." : $("error-text").textContent;
      failed(s, message);
    };
    s.clock = setInterval(() => {
      const elapsed = Math.floor((Date.now() - s.started) / 1000);
      $("timer").textContent = `${String(Math.floor(elapsed / 60)).padStart(2,"0")}:${String(elapsed % 60).padStart(2,"0")}`;
    }, 1000);
  } catch (error) {
    if (current === s && !s.disposed) showDiagnostic({component:setupComponent, stage:setupStage,
      category:error.name === "NotAllowedError" ? "microphone_denied" : "invalid_data_or_configuration"});
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
  updateEngineUI(); controls(false);
}
$("voice-engine").onchange = () => { if (!current) updateEngineUI(); };
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
$("edit-asr").onclick = () => { $("prompt-dialog").showModal(); $("asr-prompt").focus(); };
$("edit-extraction").onclick = () => { $("prompt-dialog").showModal(); $("extraction-prompt").focus(); };
function editorSettings() {
  const conversation = $("prompt").value.trim(), extraction = $("extraction-prompt").value.trim();
  const s2s_conversation = $("s2s-prompt").value.trim();
  const s2s_first_message = $("s2s-first-message").value.trim();
  const asr_prompt = $("asr-prompt").value.trim();
  const asr_keyterms = [...new Set($("asr-keyterms").value.split(/\r?\n/).map(term => term.trim()).filter(Boolean))];
  if (!conversation || conversation.length > 16000 || !extraction || extraction.length > 16000 || !s2s_conversation || s2s_conversation.length > 16000)
    throw new Error("Conversation and extraction prompts must each contain 1–16,000 characters.");
  if (!$("greeting").value.trim()) throw new Error("Enter an opening message.");
  if (!s2s_first_message || s2s_first_message.length > 500) throw new Error("Enter a speech-to-speech first message of 1–500 characters.");
  if (asr_prompt.length > 2000) throw new Error("ASR context must be at most 2,000 characters.");
  if (asr_keyterms.length > 50 || asr_keyterms.some(term => [...term].length > 64))
    throw new Error("Use up to 50 distinct vocabulary terms, with at most 64 characters per term.");
  return {conversation, s2s_conversation, s2s_first_message, extraction, asr_prompt, asr_keyterms};
}
function fillEditor(settings) {
  $("prompt").value = settings.conversation;
  $("s2s-prompt").value = settings.s2s_conversation;
  $("s2s-first-message").value = settings.s2s_first_message;
  $("extraction-prompt").value = settings.extraction;
  $("asr-prompt").value = settings.asr_prompt;
  $("asr-keyterms").value = settings.asr_keyterms.join("\n");
}
async function prepareOpening(text) {
  const response = await fetch('/playground/first-message/prepare', {method:'POST',
    headers:{'Content-Type':'application/json'}, body:JSON.stringify({text})});
  if (!response.ok) throw new Error('Could not prepare the exact first message. Check Gemini access and try again.');
}
$("use-prompt").onclick = async () => {
  try {
    const settings = editorSettings();
    if (selectedEngine() === 's2s') {
      $("save-note").textContent = 'Preparing the first message…';
      await prepareOpening(settings.s2s_first_message);
    }
  } catch (error) { $("save-note").textContent = error.message; return; }
  $("prompt-note").textContent = "Ready for your next conversation"; $("prompt-dialog").close();
};
$("default-prompt").onclick = () => {
  fillEditor(defaults); $("greeting").value = config.greeting;
  $("save-note").textContent = "Defaults restored in this editor. Save to keep them after a refresh.";
};
$("save-prompt").onclick = async () => {
  try {
    const settings = editorSettings();
    if (config?.s2s_ready && (selectedEngine() === 's2s' || settings.s2s_first_message !== savedFirstMessage)) {
      $("save-note").textContent = 'Preparing the first message…';
      await prepareOpening(settings.s2s_first_message);
    }
    const response = await fetch("/playground/prompts", {method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({...settings, save: true})});
    if (!response.ok) throw new Error("Could not save. Check the prompt length and local server.");
    savedFirstMessage = settings.s2s_first_message;
    $("save-note").textContent = "Settings saved. The speech-to-speech first message also applies to future Gemini phone calls. The cascaded opening is page-only.";
  } catch (error) { $("save-note").textContent = error.message; }
};
$("patient-form").onsubmit = event => { event.preventDefault(); start(); };
$("download").onclick = () => {
  if (savedCall) window.location.href = `/playground/calls/${savedCall.number}/pdf`;
};
async function refreshCalls() {
  try {
    const response = await fetch("/playground/calls", {cache: "no-store"});
    if (!response.ok) throw new Error("Could not load saved calls.");
    const calls = await response.json();
    $("call-list").replaceChildren();
    const statuses = {in_call: "In progress", finalizing: "Saving call…", complete: "PDF saved", partial: "Partial · PDF saved", dropped: "Dropped · no PDF", interrupted: "Interrupted · no PDF", summary_failed: "Summary failed · no PDF", pdf_failed: "PDF save failed", save_failed: "Call save failed", recording_failed: "Recording save failed"};
    for (const call of calls) {
      const row = document.createElement("tr");
      for (const value of [String(call.number).padStart(3, "0"), call.source === "phone" ? "Phone" : "Browser", call.label || call.name, call.age ?? "—", call.created_at.replace("T", " "), statuses[call.status] || call.status]) {
        const cell = document.createElement("td"); cell.textContent = value; row.append(cell);
      }
      const cell = document.createElement("td");
      if (["complete", "partial"].includes(call.status)) {
        const link = document.createElement("a"); link.href = `/playground/calls/${call.number}/pdf`;
        link.textContent = call.filename; cell.append(link);
      } else cell.textContent = "—";
      row.append(cell);
      const review = document.createElement("td");
      if (call.source === "phone") {
        const link = document.createElement("a");
        link.href = `/calls/${encodeURIComponent(call.session_id)}`;
        link.textContent = "Transcript & audio"; review.append(link);
        if (call.audio_available) {
          const download = document.createElement("a");
          download.href = `${link.getAttribute("href")}/audio`;
          download.textContent = "Download mono audio";
          review.append(document.createElement("br"), download);
        }
      } else review.textContent = "—";
      row.append(review);
      const actions = document.createElement("td");
      const remove = document.createElement("button");
      remove.type = "button"; remove.className = "secondary delete-call";
      remove.textContent = "Delete";
      remove.setAttribute("aria-label", `Delete call ${call.number}: ${call.label || call.name}`);
      remove.disabled = ["in_call", "finalizing"].includes(call.status);
      remove.title = remove.disabled ? "Wait until this call finishes saving" : "Delete this saved call";
      remove.onclick = async () => {
        if (!window.confirm(`Delete call ${call.number}: ${call.label || call.name}?\n\nThis removes its saved transcript, recording and PDF from the website. You cannot undo this here.`)) return;
        remove.disabled = true;
        try {
          const response = await fetch(`/playground/calls/${call.number}`, {method: "DELETE"});
          if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || "Could not delete this call.");
          }
          if (savedCall?.number === call.number) { savedCall = null; $("download").disabled = true; }
          await refreshCalls();
          $("calls-note").textContent = `Call ${call.number} deleted.`;
        } catch (error) {
          $("calls-note").textContent = error.message; remove.disabled = false;
        }
      };
      actions.append(remove); row.append(actions); $("call-list").append(row);
    }
    $("calls-note").textContent = calls.length ? "" : "No calls yet. Enter a name and age to begin.";
  } catch (error) { $("calls-note").textContent = error.message; }
}
$("refresh-calls").onclick = refreshCalls;
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
    savedFirstMessage = data.s2s_first_message;
    fillEditor(data); $("greeting").value = config.greeting;
    $("prompt-note").textContent = "Included intake prompt · edit to customize";
    $("start").disabled = false;
  } catch (error) { showError(error.message); }
  refreshCalls();
  animate();
}
initialize();
