const $ = id => document.getElementById(id);
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let state = null, media = {}, mode = 'replay', busy = false, playbackToken = 0, playing = null;
const dateLabel = value => new Date(value + 'T12:00:00Z').toLocaleDateString('en-GB', {day:'numeric',month:'short',timeZone:'UTC'});
const stamp = value => value ? new Date(value).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'}) : 'Not recorded';
const changes = {worse:'Worse than yesterday',same:'No reported change',better:'Reported improvement',unknown:'Change unclear'};
const names = {pain:'Pain',vision:'Seeing'};
const mediaFor = turn => turn?.audio || (media[turn?.id]?.text === turn?.text ? media[turn.id] : null);
const recent = () => state?.reports?.length > 1 ? state.reports.at(-1) : null;

async function api(path, body) {
  const response = await fetch('/recovery/api/' + path, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  if (!response.ok) {
    let message = 'The action did not complete. The saved report has not been replaced by a replay.';
    try { const result = await response.json(); if (result.state) setState(result.state); if (typeof result.detail === 'string') message = result.detail; } catch {}
    throw new Error(message);
  }
  return response.json();
}
function showError(message) { $('error').textContent = message; $('error').hidden = !message; }
function setBusy(value) {
  busy = value;
  for (const id of ['replay-worsening','replay-stable','replay-missing','replay-contradictory','replay-correction','live-start','live-submit','reset-confirm','acknowledge','record-disposition','transfer-failed']) $(id).disabled = value;
  if (!value && state) setActionAvailability();
}
function setActionAvailability() {
  const h = state.handover;
  $('acknowledge').disabled = busy || !h || h.status !== 'review_requested';
  $('record-disposition').disabled = busy || !h || h.status !== 'acknowledged';
  $('transfer-failed').disabled = busy || !h;
}
function setState(next) { state = next; render(); }
window.recoveryDemo = {setState,setBusy,showError,isBusy:()=>busy};

function observations(report) { return report?.extraction?.observations ?? []; }
function observationButton(report, obs, text, className='') {
  return `<button class="${className}" data-report="${escape(report.id)}" data-observation="${escape(obs.id)}" title="Open supporting patient statement">${escape(text)}</button>`;
}
function renderSymptoms(report, baseline=false) {
  if (!report) return '<p class="awaiting">A new conversation.<br>A change worth hearing.</p>';
  return ['pain','vision'].map(symptom => {
    const items = observations(report).filter(o => o.symptom === symptom);
    if (!items.length) return `<div class="symptom-item"><span>${names[symptom]}</span><strong>Not reported</strong></div>`;
    return items.map(obs => `<div class="symptom-item"><span>${names[symptom]}${obs.superseded_by ? ' · corrected later' : obs.corrects ? ' · correction' : ''}</span>${observationButton(report,obs,baseline ? (symptom==='pain'?'Mild pain reported':'No change reported') : (obs.superseded_by?'Earlier: ':'') + (changes[obs.change] || obs.description), obs.change === 'worse' ? 'worse' : '')}</div>`).join('');
  }).join('');
}
function render() {
  const e = state.episode, prev = state.reports[0], current = recent(), h = state.handover;
  $('patient-name').textContent = `${e.patient.name} · ${e.patient.age}`;
  $('patient-identity').textContent = `Synthetic patient · selected recovery episode`;
  $('procedure').textContent = `${e.procedure} · ${e.operated_eye.toLowerCase()} eye`;
  $('procedure-date').textContent = dateLabel(e.procedure_date) + ' 2026';
  $('pod').textContent = `Day ${e.postoperative_day}`;
  $('previous-date').textContent = dateLabel(prev.date) + ` · day ${prev.postoperative_day ?? 2}`;
  $('today-date').textContent = dateLabel(e.today) + ` · day ${e.postoperative_day}`;
  $('previous-symptoms').innerHTML = renderSymptoms(prev,true);
  $('current-symptoms').innerHTML = renderSymptoms(current);
  document.querySelector('.report-card.today').classList.toggle('worsened',current?.decision.status === 'review_requested');
  $('report-result').textContent = !current ? 'No report yet. Missing answers are never treated as normal.' : current.decision.status === 'report_saved' ? 'Report saved · not clinical clearance. Scheduled review remains.' : 'Change or uncertainty · local staff review requested.';
  const question = state.protocol.questions[0];
  $('opening-hi').textContent = question.hi; $('opening-en').textContent = question.en;
  $('call-state').textContent = !current ? 'Ready to replay' : current.decision.status === 'review_requested' ? 'Routine questions paused' : 'Report saved';
  $('patient-response').hidden = !current;
  $('agent-outcome').hidden = !current;
  if (current) {
    const turns = current.turns.filter(t => t.role === 'patient');
    $('patient-response').classList.toggle('worsened',current.decision.status === 'review_requested');
    $('patient-response').innerHTML = '<span class="speaker">PATIENT · EXACT WORDS</span>' + (turns.length ? turns.map(t => `<button data-report="${escape(current.id)}" data-turn="${escape(t.id)}" lang="hi" title="Read transcript and audio source">“${escape(t.text)}”</button>${t.subtitle ? `<p class="subtitle">${escape(t.subtitle)}</p>` : ''}`).join('') : '<p>No patient answer captured.</p><p class="subtitle">Silence is missing information, never normal recovery.</p>');
    const outcome = state.protocol.messages[current.decision.status];
    $('agent-outcome').innerHTML = outcome ? `<span class="speaker">AGENT · ${current.decision.status==='review_requested'?'CHANGES COURSE':'REPORT SAVED'}</span><p lang="hi">${escape(outcome.hi)}</p><p class="subtitle">${escape(outcome.en)}</p>` : '';
  }
  $('handover-empty').hidden = !!h; $('handover-content').hidden = !h;
  $('journey-handover').classList.toggle('active',!!h);
  if (h) renderHandover(h,e);
  $('call-history').innerHTML = state.calls.length ? state.calls.map(c => `<div class="call-row">${escape(dateLabel(c.date))} · ${escape(c.status.replaceAll('_',' '))}<span>${escape(c.mode.replaceAll('_',' '))} · ${escape(c.id)}</span></div>`).join('') : '<p class="small muted">The prepared previous report is the baseline. No new follow-up has run yet.</p>';
  $('protocol-content').textContent = JSON.stringify({version:state.protocol.version.replace('-demo',''),approval:'Illustrative; not clinically approved',rules:state.protocol.rules.map(({label,condition,action,urgency})=>({label,condition,action,urgency})),fallback:state.protocol.fallback_note},null,2);
  renderSource(e);
  setActionAvailability();
}
function renderHandover(h,e) {
  const statuses = {review_requested:'Review requested',acknowledged:'Acknowledged by staff',disposition_recorded:'Disposition recorded'};
  $('handover-status').textContent = statuses[h.status] || h.status;
  $('handover-status').classList.toggle('acknowledged',h.status !== 'review_requested');
  $('handover-subtitle').textContent = h.status === 'review_requested' ? 'Waiting for a local staff action. Contact and care are not confirmed.' : h.status === 'acknowledged' ? `${h.staff || 'Staff'} has acknowledged. Clinical resolution is not recorded.` : 'A staff disposition is saved. Clinical resolution is not recorded.';
  if (h.transfer_status === 'failed') $('handover-subtitle').textContent = 'Simulated telephone transfer failed · unresolved. No telephone contact or care is confirmed.';
  $('handover-subtitle').classList.toggle('transfer-unresolved',h.transfer_status === 'failed');
  const reports = state.reports.filter(r => h.report_ids.includes(r.id));
  const latest = reports.at(-1), prev = state.reports[0];
  let summary = `<div class="summary-line"><span>EPISODE · CLINICIAN FIXTURE</span><button class="summary-evidence" data-source-open>${escape(e.procedure)} · ${escape(e.operated_eye)} eye · postoperative day ${e.postoperative_day} ↗</button></div>`;
  summary += `<div class="summary-line"><span>PREVIOUS REPORT · ${escape(dateLabel(prev.date))}</span><button class="summary-evidence" data-report="${escape(prev.id)}">Mild pain; no reported change in seeing ↗</button></div>`;
  if (latest) {
    summary += `<div class="summary-line"><span>NEW PATIENT REPORT · ${escape(dateLabel(latest.date))}</span>`;
    summary += observations(latest).map(obs => observationButton(latest,obs,obs.description + (obs.superseded_by ? ' (corrected later)' : obs.corrects ? ' (explicit correction)' : '') + ' ↗','summary-evidence')).join('<br>');
    if (!observations(latest).length) summary += 'No verified symptom statement available.';
    summary += '</div>';
    const issues = [...new Set([...(latest.extraction.uncertainties || []),...(latest.decision.issues || [])])];
    if (issues.length) summary += `<div class="summary-line"><span>UNCERTAINTY · REVIEW REQUIRED</span>${issues.map(escape).join('<br>')}</div>`;
  }
  if (h.disposition) summary += `<div class="summary-line"><span>STAFF DISPOSITION · ${escape(h.disposition.staff)}</span>${escape(h.disposition.note)}</div>`;
  $('handover-summary').innerHTML = summary;
  $('criterion').innerHTML = '<span class="eyebrow">WHY THE AGENT CHANGED COURSE</span>' + h.criterion_ids.map(id => {
    const rule = state.protocol.rules.find(r=>r.id===id);
    return `<strong>${escape(rule?.label || id)}</strong><span class="small">${escape(rule?.condition || "Review required")}</span>`;
  }).join('') + `<br><button class="text-button" data-protocol-open>Illustrative protocol ${escape(h.protocol_version.replace('-demo',''))} · inspect rule ↗</button>`;
  $('acknowledge').textContent = h.status === 'review_requested' ? 'Acknowledge review' : '✓ Acknowledgement recorded';
  $('disposition-controls').hidden = h.status === 'review_requested';
  $('audit').innerHTML = state.audit.map(a => `<li><strong>${escape(a.action.replaceAll('_',' '))}</strong>${a.staff?` · ${escape(a.staff.replace('demo operator','Local operator'))}`:''}<br><time>${escape(stamp(a.at))}</time>${a.note?`<br>${escape(a.note)}`:''}</li>`).join('');
  $('transfer-state').textContent = h.transfer_status === 'failed' ? 'Simulated telephone transfer failed · unresolved. No care confirmed. No approved fallback instructions are available.' : 'Telephone transfer not attempted. This screen is the local handover destination.';
}
function renderSource(e) {
  $('source-content').innerHTML = `<p>Prepared fictional records are separate from patient-reported recovery and AI extraction.</p><div class="source-block"><h3>History intake · ${escape(dateLabel(e.intake_review.date))}</h3><p>${escape(e.intake_review.source)}</p><blockquote lang="hi">${escape(e.intake_review.patient_report)}</blockquote><p>${escape(e.intake_review.summary)}</p><p><strong>${escape(e.intake_review.author.replace('Demo ',''))}</strong> · ${escape(e.intake_review.status)}</p><a href="/playground">Open existing history intake & PDF workflow ↗</a></div><div class="source-block"><h3>Prepared discharge record · ${escape(dateLabel(e.discharge.date))}</h3><dl><dt>Source</dt><dd>${escape(e.discharge.source)}</dd><dt>Author</dt><dd>${escape(e.discharge.author.replace('Demo ',''))}</dd><dt>Procedure</dt><dd>${escape(e.procedure)}</dd><dt>Operated eye</dt><dd>${escape(e.operated_eye)}</dd><dt>Procedure date</dt><dd>${escape(e.procedure_date)}</dd><dt>Scheduled review</dt><dd>${escape(e.discharge.scheduled_review_date)} · remains scheduled</dd></dl><p>${escape(e.discharge.summary)}</p></div><div class="source-block"><h3>Identity & episode boundary</h3><p>${escape(e.identity_basis)}</p><p>Only this selected episode supplies this context. It is never copied into an unrelated intake or episode.</p></div>`;
}
function showEvidence(reportId, observationId, turnId) {
  const report = state.reports.find(r=>r.id===reportId); if (!report) return;
  const obs = observationId && observations(report).find(o=>o.id===observationId);
  const refs = obs ? obs.evidence : report.turns.filter(t=>t.role==='patient' && (!turnId || t.id===turnId)).map(t=>({turn_id:t.id,quote:t.text}));
  $('evidence-content').innerHTML = `<p><strong>${escape(dateLabel(report.date))} 2026 · patient-reported information</strong><br>${escape(report.extraction_source.replaceAll('_',' '))}. These words are not confirmed clinical findings.</p>` + (obs ? `<p>${escape(obs.description)}${obs.corrects ? ' · Explicit correction of ' + escape(obs.corrects) : ''}${obs.superseded_by ? ' · Superseded by patient correction ' + escape(obs.superseded_by) : ''}</p>` : '') + (refs.length ? refs.map(ref => {
    const turn = report.turns.find(t=>t.id===ref.turn_id && t.role==='patient');
    if (!turn || !turn.text.includes(ref.quote)) return '<p class="error">Evidence reference could not be verified. No quote or audio is presented for this assertion.</p>';
    const text = escape(turn.text), quote = escape(ref.quote);
    const audio = mediaFor(turn);
    const available = audio && audio.url && Number.isFinite(audio.start) && Number.isFinite(audio.end) && audio.end > audio.start;
    return `<div class="evidence-turn"><div class="turn-meta">${escape(turn.id)} · FULL PATIENT TURN</div><blockquote lang="hi">${text.replace(quote,`<mark>${quote}</mark>`)}</blockquote>${turn.subtitle?`<p>${escape(turn.subtitle)}</p>`:''}${available ? `<button class="secondary" data-audio-report="${escape(report.id)}" data-audio-turn="${escape(turn.id)}">▶ Play source segment</button><p class="small">${escape(audio.label || 'Generated synthetic speech · not a call recording')} · ${escape(audio.generator || 'synthetic audio')}<br>${audio.start.toFixed(2)}–${audio.end.toFixed(2)} s · full source clip; no isolated speaker tracks claimed.</p>` : '<button class="secondary" disabled>Audio unavailable</button><p class="small">No recording or aligned source segment exists for this turn.</p>'}</div>`;
  }).join('') : '<p>No patient transcript turn is available. Missing answers do not indicate normal recovery.</p>');
  $('evidence-dialog').showModal();
}
function stopAudio() { playbackToken++; if (playing) { playing.pause(); playing.dispatchEvent(new Event('abort')); playing=null; } $('stop-replay').hidden=true; }
async function playSegment(source, token) {
  if (token !== playbackToken) return;
  if (!source?.url) throw new Error('Generated speech is unavailable for this turn. Transcript remains available.');
  const a = new Audio(source.url); playing=a;
  await new Promise((resolve,reject) => {
    let done=false;
    const finish=err=>{if(done)return;done=true;a.pause();clearTimeout(timer);if(playing===a)playing=null;err?reject(err):resolve();};
    const timer=setTimeout(()=>finish(new Error('Audio playback did not finish. Transcript remains available.')),Math.max(15000,((source.end||30)-(source.start||0))*1000+10000));
    a.addEventListener('error',()=>finish(new Error('Generated audio could not play. Transcript remains available.')),{once:true});
    a.addEventListener('abort',()=>finish(),{once:true});a.addEventListener('ended',()=>finish(),{once:true});
    a.addEventListener('timeupdate',()=>{if(Number.isFinite(source.end)&&a.currentTime>=source.end)finish();});
    a.addEventListener('loadedmetadata',()=>{a.currentTime=source.start||0;a.play().catch(()=>finish(new Error('Audio playback was blocked. Use Play source segment or continue with captions.')));},{once:true});
    a.load();
  });
}
async function replay(branch) {
  if(busy)return; stopAudio();showError('');setBusy(true);$('activity').textContent='Applying the fixture extraction to the recovery rules…';
  let pending=null;
  try {
    pending=await api('replay',{branch});
    if($('speak-replay').checked) {
      const report=pending.reports.at(-1),token=playbackToken;
      $('stop-replay').hidden=false;
      const question=pending.protocol.questions[0];
      $('activity').textContent='Generated replay · agent asks about yesterday';
      await playSegment(media['question-'+question.id],token);
      for(const turn of report.turns.filter(t=>t.role==='patient')) {
        if(token!==playbackToken)break;
        $('replay-caption').hidden=false;
        $('replay-caption').innerHTML=`<span class="speaker">GENERATED REPLAY · PATIENT WORDS</span><p lang="hi">“${escape(turn.text)}”</p><p class="subtitle">${escape(turn.subtitle)}</p>`;
        $('activity').textContent='Generated replay · listening to the patient report';
        await playSegment(mediaFor(turn),token);
      }
      $('replay-caption').hidden=true;
      // This is the actual saved rule result, revealed after the patient source.
      setState(pending);pending=null;
      if(token===playbackToken) {
        $('activity').textContent='Generated replay · protocol response';
        await playSegment(media['message-'+report.decision.status],token);
        $('activity').textContent='Replay complete · generated speech, not a call recording.';
      }
    } else {
      setState(pending);pending=null;
      $('activity').textContent='Saved locally · precomputed synthetic extraction, actual rule evaluation.';
    }
  } catch(error) {showError(error.message);$('activity').textContent='The actual saved result remains visible; audio was not substituted.';} finally {
    if(pending)setState(pending);
    $('replay-caption').hidden=true;$('stop-replay').hidden=true;setBusy(false);
  }
}
async function staff(action) {
  if(busy)return;
  const staffName=$('staff-name').value.trim(),note=action==='disposition'?$('disposition-note').value.trim():'';
  if(!staffName || (action==='disposition'&&!note)){showError('Enter a staff name and, for a disposition, a note describing the decision.');return;}
  showError('');setBusy(true);
  try{setState(await api('staff',{action,staff:staffName,note,expected_revision:state.revision}));$('activity').textContent='Staff action recorded locally with its actual timestamp.';if(action==='disposition')$('disposition-note').value='';}catch(e){showError(e.message);}finally{setBusy(false);}
}
function switchMode(next) {
  stopAudio();mode=next;
  $('replay-mode').classList.toggle('selected',next==='replay');$('live-mode').classList.toggle('selected',next==='live');
  $('replay-mode').setAttribute('aria-pressed',String(next==='replay'));$('live-mode').setAttribute('aria-pressed',String(next==='live'));
  $('replay-controls').hidden=next!=='replay';$('live-controls').hidden=next!=='live';
  $('conversation-label').textContent=next==='live'?'LIVE MICROPHONE · SYNTHETIC ROLE-PLAY':'SYNTHETIC FOLLOW-UP';
  $('activity').textContent='';window.dispatchEvent(new CustomEvent('recovery-mode-change',{detail:next}));
}
$('replay-mode').onclick=()=>switchMode('replay');$('live-mode').onclick=()=>switchMode('live');
for(const branch of ['stable','worsening','missing','contradictory','correction'])$('replay-'+branch).onclick=()=>replay(branch);
$('stop-replay').onclick=()=>{stopAudio();$('activity').textContent='Replay audio stopped. The saved report remains available.';};
$('speak-replay').onchange=()=>{if(!$('speak-replay').checked)stopAudio();};
$('staff-name').addEventListener('input',()=>{$('staff-actor').textContent=$('staff-name').value.trim()||'unnamed staff';});
$('acknowledge').onclick=()=>staff('acknowledge');$('record-disposition').onclick=()=>staff('disposition');$('transfer-failed').onclick=()=>staff('transfer_failed');
$('previous-evidence').onclick=()=>showEvidence(state.reports[0].id);
$('source-open').onclick=()=>$('source-dialog').showModal();$('protocol-open').onclick=()=>$('protocol-dialog').showModal();$('reset-open').onclick=()=>$('reset-dialog').showModal();
$('reset-confirm').onclick=async()=>{stopAudio();switchMode('replay');setBusy(true);showError('');try{setState(await api('reset',{}));$('reset-dialog').close();$('activity').textContent='Synthetic episode reset. Existing intake, PDF and recording records were not changed.';}catch(e){showError(e.message);}finally{setBusy(false);}};
$('live-form').onsubmit=async(event)=>{event.preventDefault();if(busy)return;showError('');setBusy(true);$('activity').textContent='Extracting this synthetic reply with the configured live model…';try{setState(await api('report',{text:$('live-text').value,expected_revision:state.revision}));$('activity').textContent='Live-model extraction evaluated and saved. No replay was substituted.';}catch(e){showError(e.message);$('activity').textContent='Live extraction failed. No replay was substituted.';}finally{setBusy(false);}};
document.addEventListener('click',async event=>{
  const button=event.target.closest('button');if(!button)return;
  if(button.hasAttribute('data-close'))button.closest('dialog').close();
  if(button.hasAttribute('data-source-open'))$('source-dialog').showModal();
  if(button.hasAttribute('data-protocol-open'))$('protocol-dialog').showModal();
  if(button.dataset.report)showEvidence(button.dataset.report,button.dataset.observation,button.dataset.turn);
  if(button.dataset.audioTurn){const report=state.reports.find(r=>r.id===button.dataset.audioReport),turn=report?.turns.find(t=>t.id===button.dataset.audioTurn);stopAudio();const token=playbackToken;button.disabled=true;try{await playSegment(mediaFor(turn),token);}catch(e){showError(e.message);}finally{button.disabled=false;}}
});
$('evidence-dialog').addEventListener('close',stopAudio);
window.addEventListener('beforeunload',stopAudio);
try {const [loaded,clips]=await Promise.all([api('state'),api('media').catch(()=>({}))]);media=clips;setState(loaded);$('audio-mode').textContent=Object.keys(media).length?'Generated Hindi speech · not a call recording':'Audio unavailable · transcript replay works';}catch(error){showError(error.message);}
