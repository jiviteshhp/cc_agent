// Optional live microphone mode. Reuses the intake capture worklet and providers.
// No browser speech-recognition fallback and no conversion to synthetic replay.
const $ = id => document.getElementById(id);
let active = null;
const status = text => { if ($('live-status')) $('live-status').textContent = text; };
const controls = running => {
  $('live-start').disabled = running;
  $('live-stop').disabled = !running;
  $('live-cancel').disabled = !running;
};
async function dispose(s, message) {
  if (!s || s.disposed) return;
  s.disposed = true; s.listening = false;
  clearTimeout(s.timer); clearTimeout(s.recordTimer);
  s.abort?.abort(); s.captureReject?.(new Error("Capture cancelled"));
  s.capture?.port.postMessage('destroy');
  for (const node of s.sources) { try { node.stop(); } catch {} }
  s.mic?.getTracks().forEach(track => track.stop());
  s.input?.disconnect(); s.capture?.disconnect(); s.zero?.disconnect();
  if (s.ws?.readyState === WebSocket.OPEN) s.ws.send(JSON.stringify({type: 'cancel'}));
  s.ws?.close();
  await s.ctx?.close().catch(() => {});
  if (active === s) {
    active = null;
    window.recoveryDemo?.setBusy(false);
    controls(false);
    if (message) status(message);
  }
}
function fail(s, message) {
  if (s !== active || s.disposed) return;
  window.recoveryDemo?.showError(message);
  dispose(s, message);
}
function playback(s, encoded) {
  const bytes = Uint8Array.from(atob(encoded), c => c.charCodeAt(0));
  if (bytes.length % 2 || bytes.length > 480000) throw new Error('Invalid speech audio');
  const view = new DataView(bytes.buffer);
  const buffer = s.ctx.createBuffer(1, bytes.length / 2, 24000);
  const channel = buffer.getChannelData(0);
  for (let i = 0; i < channel.length; i++) channel[i] = view.getInt16(i * 2, true) / 32768;
  s.next = Math.max(s.next, s.ctx.currentTime + .08);
  if (s.next - s.ctx.currentTime > 40) throw new Error('Speech playback exceeded the local buffer');
  const source = s.ctx.createBufferSource(); source.buffer = buffer;
  source.connect(s.ctx.destination); s.sources.add(source);
  source.onended = () => s.sources.delete(source);
  source.start(s.next); s.next += buffer.duration;
}
function recordWhenOpeningEnds(s) {
  const wait = Math.max(0, s.next - s.ctx.currentTime) * 1000 + 100;
  status('Agent speaking · microphone will listen after the question');
  s.recordTimer = setTimeout(() => {
    if (active !== s || s.disposed || s.ws.readyState !== WebSocket.OPEN) return;
    s.listening = true;
    s.ws.send(JSON.stringify({type: 'record'}));
    status('Listening · speak naturally, or select Finish reply');
  }, wait);
}
async function start() {
  if (active || window.recoveryDemo?.isBusy?.()) return;
  const s = {sources: new Set(), next: 0, listening: false, disposed: false};
  active = s; window.recoveryDemo?.setBusy(true); controls(true);
  $('live-transcript').textContent = '';
  status('Requesting microphone · synthetic patient only');
  s.timer = setTimeout(() => fail(s, 'Live setup timed out. No replay was substituted.'), 45000);
  try {
    s.ctx = new AudioContext({sampleRate: 48000}); await s.ctx.resume();
    const mic = await navigator.mediaDevices.getUserMedia({audio: {channelCount: 1, echoCancellation: true,
      noiseSuppression: true, autoGainControl: false}, video: false});
    if (s.disposed) { mic.getTracks().forEach(track => track.stop()); return; }
    s.mic = mic; s.abort = new AbortController();
    const wasm = await fetch('/playground/assets/rnnoise.wasm', {signal: s.abort.signal});
    if (!wasm.ok) throw new Error('Microphone filtering unavailable');
    const wasmBinary = await wasm.arrayBuffer();
    await s.ctx.audioWorklet.addModule('/playground/assets/capture-worklet.js');
    if (s.disposed) return;
    s.input = s.ctx.createMediaStreamSource(mic);
    s.capture = new AudioWorkletNode(s.ctx, 'pcm-capture', {numberOfInputs: 1, numberOfOutputs: 1,
      channelCount: 1, processorOptions: {wasmBinary}});
    s.zero = s.ctx.createGain(); s.zero.gain.value = 0;
    s.input.connect(s.capture); s.capture.connect(s.zero); s.zero.connect(s.ctx.destination);
    await new Promise((resolve, reject) => {
      s.captureReject = reject;
      s.capture.onprocessorerror = () => { reject(new Error('Microphone capture failed')); fail(s, 'Microphone capture failed.'); };
      s.capture.port.onmessage = ({data}) => {
        if (data.type === 'ready') { s.captureReject = null; resolve(); return; }
        if (data.type === 'error') { reject(new Error('Microphone filtering failed')); fail(s, 'Microphone filtering failed.'); return; }
        if (!s.listening || s.disposed || s.ws?.readyState !== WebSocket.OPEN) return;
        if (s.ws.bufferedAmount > 32000) { fail(s, 'Live microphone transport is falling behind.'); return; }
        s.ws.send(data.pcm);
      };
    });
    if (s.disposed) return;
    s.ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/recovery/voice`);
    s.ws.onmessage = ({data}) => {
      if (active !== s || s.disposed) return;
      try {
        const event = JSON.parse(data);
        if (event.type === 'status') {
          status(event.data);
          if (event.data.startsWith('Finalizing')) s.listening = false;
        } else if (event.type === 'assistant') {
          status(event.data.stage === 'opening' ? 'Agent question · live provider speech' : 'Agent response · live provider speech');
          $('live-transcript').textContent = event.data.text;
        } else if (event.type === 'audio') playback(s, event.data);
        else if (event.type === 'ready') { clearTimeout(s.timer); recordWhenOpeningEnds(s); }
        else if (event.type === 'transcript') {
          $('live-transcript').textContent = event.data.text;
          $('live-transcript').dataset.final = String(event.data.final);
        } else if (event.type === 'result') {
          s.listening = false; s.gotResult = true;
          window.recoveryDemo?.setState(event.data);
        } else if (event.type === 'complete') {
          if (!s.gotResult) { fail(s, 'Live completion did not include a saved report. Review remains unconfirmed.'); return; }
          s.complete = true;
          const remaining = Math.max(0, s.next - s.ctx.currentTime) * 1000 + 100;
          s.timer = setTimeout(() => dispose(s, 'Live report saved · no call recording retained'), remaining);
        } else if (event.type === 'error') fail(s, event.data);
      } catch { fail(s, 'The live voice response could not be read. No replay was substituted.'); }
    };
    s.ws.onerror = () => fail(s, 'Live voice could not connect. Check local provider configuration.');
    s.ws.onclose = () => {
      if (!s.disposed && !s.complete) fail(s, s.gotResult ?
        'Report saved; live speech ended before confirmed playback.' :
        'Live connection ended before completion. No recovery conclusion was made.');
    };
  } catch (error) {
    if (!s.disposed) fail(s, error.name === 'NotAllowedError' ? 'Microphone permission was not granted.' :
      'Live microphone setup failed. Check microphone and provider access; no replay was substituted.');
  }
}
$('live-start')?.addEventListener('click', start);
$('live-stop')?.addEventListener('click', () => {
  if (active?.listening && active.ws?.readyState === WebSocket.OPEN) {
    active.listening = false; active.ws.send(JSON.stringify({type: 'finish'}));
    $('live-stop').disabled = true; status('Finalizing the patient report…');
  }
});
$('live-cancel')?.addEventListener('click', () => dispose(active, 'Live follow-up cancelled · completion not confirmed'));
window.addEventListener('recovery-mode-change', event => {
  if (event.detail !== 'live') dispose(active, 'Live microphone stopped');
});
window.addEventListener('pagehide', () => dispose(active));
controls(false);
