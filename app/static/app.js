/* 發音練習實驗室 — 前端邏輯（無框架） */
'use strict';

const $ = (id) => document.getElementById(id);
const MAX_RECORD_MS = 15000;

const state = {
  lang: 'en',
  sentences: { en: [], zh: [] },
  current: null,
  records: [],
  blob: null,
  mime: '',
  recorder: null,
  chunks: [],
  stream: null,
  audioCtx: null,
  analyser: null,
  raf: null,
  startedAt: 0,
  timerId: null,
  levels: [],
  recording: false,
  submitting: false,
  result: null,
  feedback: {},
  feedbackSaved: false,
};

/* ---------------- 初始化 ---------------- */
async function init() {
  bind();
  await loadSentences();
  pickSentence(true);
  refreshCost();
  loadRecordFromUrl();
}

/* ?record=last 或 ?record=<record_id> 可直接重看某一筆結果（研究複查用） */
async function loadRecordFromUrl() {
  const rid = new URLSearchParams(location.search).get('record');
  if (!rid) return;
  try {
    const res = await fetch('/api/records?limit=300');
    const { records } = await res.json();
    const rec = rid === 'last' ? records[0] : records.find((r) => r.record_id === rid);
    if (!rec || !rec.result) return;
    state.result = { record_id: rec.record_id, result: rec.result };
    state.current = { text: rec.sentence, id: rec.sentence_id, lang: rec.lang, level: 1, focus: '' };
    $('sentenceText').textContent = rec.sentence;
    $('pinyinText').textContent = '';
    $('focusText').textContent = `複查紀錄 ${rec.record_id}（${rec.created_at || ''}）`;
    $('results').hidden = false;
    renderResult(state.result);
    $('results').scrollIntoView({ block: 'start' });
  } catch (_) { /* ignore */ }
}

function bind() {
  $('langTabs').addEventListener('click', (e) => {
    const btn = e.target.closest('.tab');
    if (!btn) return;
    state.lang = btn.dataset.lang;
    document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t === btn));
    pickSentence(true);
  });
  $('levelSel').addEventListener('change', () => pickSentence(true));
  $('nextSentence').addEventListener('click', () => pickSentence(true));
  $('speakBtn').addEventListener('click', speak);
  $('recordBtn').addEventListener('click', () => (state.recording ? stopRecording() : startRecording()));
  $('redoBtn').addEventListener('click', resetRecording);
  $('submitBtn').addEventListener('click', submit);
  $('fileInput').addEventListener('change', onFile);
  $('saveFeedback').addEventListener('click', saveFeedback);
  $('historyBtn').addEventListener('click', toggleHistory);
  $('closeHistory').addEventListener('click', toggleHistory);
  document.querySelectorAll('.seg').forEach((seg) => {
    seg.addEventListener('click', (e) => {
      const btn = e.target.closest('button');
      if (!btn) return;
      seg.querySelectorAll('button').forEach((b) => b.classList.toggle('on', b === btn));
      state.feedback[seg.dataset.field] = btn.dataset.val;
    });
  });
}

/* ---------------- 題庫 ---------------- */
async function loadSentences() {
  const res = await fetch('/api/sentences');
  state.sentences = await res.json();
}

function pickSentence(force) {
  const maxLevel = Number($('levelSel').value) || 0;
  let pool = state.sentences[state.lang] || [];
  if (maxLevel) pool = pool.filter((s) => s.level === maxLevel);
  if (!pool.length) pool = state.sentences[state.lang] || [];
  const next = pool[Math.floor(Math.random() * pool.length)];
  if (force && next && state.current && pool.length > 1) {
    let guard = 0;
    while (next.id === state.current.id && guard++ < 8) {
      const cand = pool[Math.floor(Math.random() * pool.length)];
      if (cand.id !== state.current.id) break;
    }
  }
  state.current = next || null;
  $('sentenceText').textContent = state.current ? state.current.text : '—';
  $('pinyinText').textContent = state.current?.pinyin || '';
  const stars = '★'.repeat(state.current?.level || 1);
  $('focusText').textContent = state.current ? `${stars}　練習重點：${state.current.focus}` : '';
  resetRecording();
}

/* ---------------- 示範發音 ---------------- */
function speak() {
  if (!state.current || !window.speechSynthesis) return;
  const utter = new SpeechSynthesisUtterance(state.current.text);
  const want = state.lang === 'zh' ? ['zh-TW', 'zh-Hant', 'zh'] : ['en-US', 'en-GB', 'en'];
  const voices = speechSynthesis.getVoices();
  const voice = want.map((p) => voices.find((v) => v.lang.replace('_', '-').startsWith(p))).find(Boolean);
  if (voice) utter.voice = voice;
  utter.lang = want[0];
  utter.rate = state.lang === 'zh' ? 0.9 : 0.85;
  speechSynthesis.cancel();
  speechSynthesis.speak(utter);
}

/* ---------------- 錄音 ---------------- */
async function startRecording() {
  if (!state.current) return;
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: true, channelCount: 1 },
    });
  } catch (err) {
    toast('無法取得麥克風：' + (err.message || err.name));
    return;
  }
  state.stream = stream;
  const cands = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'];
  state.mime = cands.find((m) => window.MediaRecorder && MediaRecorder.isTypeSupported(m)) || '';
  state.recorder = new MediaRecorder(stream, state.mime ? { mimeType: state.mime } : undefined);
  state.mime = state.recorder.mimeType || state.mime || 'audio/webm';
  state.chunks = [];
  state.recorder.ondataavailable = (e) => { if (e.data && e.data.size) state.chunks.push(e.data); };
  state.recorder.onstop = finaliseRecording;
  state.recorder.start(120);

  state.recording = true;
  state.startedAt = performance.now();
  state.levels = [];
  $('recordBtn').classList.add('recording');
  $('recordBtn').querySelector('.mic-label').textContent = '錄音中…點一下停止';
  $('recordBtn').querySelector('.mic-icon').textContent = '⏹';
  $('review').hidden = true;
  $('results').hidden = true;
  startMeter(stream);
  state.timerId = setInterval(tickTimer, 100);
}

function tickTimer() {
  const ms = performance.now() - state.startedAt;
  $('recTimer').textContent = (ms / 1000).toFixed(1) + 's';
  if (ms > MAX_RECORD_MS) stopRecording();
}

function stopRecording() {
  if (!state.recording) return;
  state.recording = false;
  state.recordedMs = Math.round(performance.now() - state.startedAt);
  clearInterval(state.timerId);
  try { state.recorder.stop(); } catch (_) { /* ignore */ }
  state.stream?.getTracks().forEach((t) => t.stop());
  stopMeter();
  $('recordBtn').classList.remove('recording');
  $('recordBtn').querySelector('.mic-label').textContent = '按下開始錄音';
  $('recordBtn').querySelector('.mic-icon').textContent = '🎤';
}

function finaliseRecording() {
  const blob = new Blob(state.chunks, { type: state.mime });
  if (blob.size < 1200) { toast('錄音太短，請再試一次'); return; }
  state.blob = blob;
  $('preview').src = URL.createObjectURL(blob);
  $('review').hidden = false;
}

function resetRecording() {
  if (state.recording) stopRecording();
  state.blob = null;
  state.chunks = [];
  $('review').hidden = true;
  $('results').hidden = true;
  $('recTimer').textContent = '00.0s';
  $('fileInput').value = '';
  clearMeter();
}

function onFile(e) {
  const file = e.target.files?.[0];
  if (!file) return;
  state.blob = file;
  state.mime = file.type || 'audio/webm';
  state.recordedMs = null;
  $('preview').src = URL.createObjectURL(file);
  $('review').hidden = false;
  toast('已載入音檔：' + file.name);
}

/* ---------------- 音量表 ---------------- */
function startMeter(stream) {
  state.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  const src = state.audioCtx.createMediaStreamSource(stream);
  state.analyser = state.audioCtx.createAnalyser();
  state.analyser.fftSize = 2048;
  src.connect(state.analyser);
  const buf = new Float32Array(state.analyser.fftSize);
  const canvas = $('meter');
  const ctx = canvas.getContext('2d');

  const draw = () => {
    state.analyser.getFloatTimeDomainData(buf);
    let sum = 0;
    for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
    const rms = Math.sqrt(sum / buf.length);
    state.levels.push(Math.min(1, rms * 6));
    if (state.levels.length > 128) state.levels.shift();
    renderMeter(ctx, canvas, state.levels);
    state.raf = requestAnimationFrame(draw);
  };
  draw();
}

function renderMeter(ctx, canvas, levels) {
  const { width: w, height: h } = canvas;
  ctx.clearRect(0, 0, w, h);
  const n = 128;
  const bw = w / n;
  for (let i = 0; i < n; i++) {
    const v = levels[i] || 0;
    const bh = Math.max(2, v * (h - 4));
    ctx.fillStyle = v > 0.75 ? '#b23a3a' : v > 0.45 ? '#b07d18' : '#2f6f5e';
    ctx.globalAlpha = 0.25 + 0.75 * (i / n);
    ctx.beginPath();
    ctx.roundRect(i * bw + 0.5, (h - bh) / 2, bw - 1.2, bh, 2);
    ctx.fill();
  }
  ctx.globalAlpha = 1;
}

function stopMeter() {
  cancelAnimationFrame(state.raf);
  state.audioCtx?.close().catch(() => {});
  state.audioCtx = null;
}

function clearMeter() {
  const canvas = $('meter');
  state.levels = [];
  renderMeter(canvas.getContext('2d'), canvas, new Array(128).fill(0.02));
}

/* ---------------- 送出 ---------------- */
async function submit() {
  if (!state.blob || !state.current || state.submitting) return;
  state.submitting = true;
  $('submitBtn').disabled = true;
  $('submitBtn').textContent = '判斷中…';
  $('results').hidden = false;
  $('verdict').className = 'verdict';
  $('verdict-emoji').textContent = '⏳';
  $('verdict').querySelector('.verdict-emoji').textContent = '⏳';
  $('verdictMain').textContent = '正在判斷…';
  $('verdictSub').textContent = 'Decisions 約 1 秒，Argon 約 5–15 秒';
  $('results').scrollIntoView({ behavior: 'smooth', block: 'start' });

  const b64 = await blobToBase64(state.blob);
  const body = {
    sentence: state.current.text,
    sentence_id: state.current.id,
    lang: state.lang,
    audio: b64,
    mime: state.mime.split(';')[0],
    audio_ms: state.recordedMs || null,
    speaker: $('speakerSel').value,
    speaker_note: $('speakerNote').value.trim(),
  };

  try {
    const res = await fetch('/api/assess', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || '判斷失敗');
    state.result = data;
    state.feedback = {};
    state.feedbackSaved = false;
    renderResult(data);
    refreshCost();
  } catch (err) {
    $('verdictMain').textContent = '判斷失敗';
    $('verdictSub').textContent = String(err.message || err);
    toast('判斷失敗：' + (err.message || err));
  } finally {
    state.submitting = false;
    $('submitBtn').disabled = false;
    $('submitBtn').textContent = '重新送出 →';
  }
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1] || '');
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

/* ---------------- 結果呈現 ---------------- */
function renderResult(data) {
  const { decisions: d, argon: a, blind: b } = data.result;
  renderVerdict(d, a, b);
  renderBlind(b);
  renderDecisions(d);
  renderArgon(a);
  renderAgreement(data.result.agreement);
  resetFeedbackForm();
}

function renderVerdict(d, a, b) {
  // 判斷以「盲聽逐字比對」為主（程式算的、不受模型迎合影響），模型分數為輔
  const diff = b?.ok ? b.diff : null;
  const rate = diff ? diff.rate : null;
  const wrong = diff ? diff.words.filter((w) => w.status !== 'correct' && w.status !== 'extra') : [];
  const argonScore = a?.ok ? a.overall : null;

  let emoji = '🔁', main = '再試一次', cls = 'low';
  if (rate !== null) {
    if (rate >= 1 && (argonScore === null || argonScore >= 80)) {
      emoji = '🎉'; main = '全部唸對了！'; cls = 'good';
    } else if (rate >= 0.8) {
      emoji = '👍'; main = `差一點點，還有 ${wrong.length} 個字要修正`; cls = 'good';
    } else if (rate >= 0.5) {
      emoji = '💪'; main = `聽得懂，但有 ${wrong.length} 個字不對`; cls = 'mid';
    } else {
      emoji = '🔁'; main = '和題目差滿多的，再念一次看看'; cls = 'low';
    }
  } else if (argonScore !== null) {
    if (argonScore >= 85) { emoji = '🎉'; main = '唸得很棒！'; cls = 'good'; }
    else if (argonScore >= 70) { emoji = '👍'; main = '很不錯，再練一下'; cls = 'good'; }
    else if (argonScore >= 50) { emoji = '💪'; main = '聽得懂，但還有要修正的地方'; cls = 'mid'; }
  }

  const heard = a?.ok && a.transcript ? a.transcript : (b?.ok ? b.transcript : '');
  const parts = [];
  if (heard) parts.push(`它聽到的是：「${heard}」`);
  if (wrong.length) {
    parts.push('要注意：' + wrong.map((w) => (
      w.status === 'missing' ? `「${w.token}」沒聽到` : `「${w.token}」聽成「${w.heard}」`
    )).join('、'));
  }
  if (!parts.length && a && !a.ok) parts.push('Argon 回應失敗，僅顯示 Decisions 結果');

  $('verdict').className = 'verdict ' + cls;
  $('verdict').querySelector('.verdict-emoji').textContent = emoji;
  $('verdictMain').textContent = main;
  $('verdictSub').textContent = parts.join(' · ');
}

function renderBlind(b) {
  const box = $('blindBox');
  if (!b || !b.ok) {
    $('blindTranscript').textContent = b ? '呼叫失敗：' + (b.error || '未知錯誤') : '—';
    $('blindWords').innerHTML = '';
    $('blindScore').textContent = '';
    $('blindMeta').textContent = '';
    $('blindMeta').style.display = 'none';
    return;
  }
  $('blindMeta').style.display = '';
  $('blindTranscript').textContent = b.transcript || '（完全沒有聽到語音）';
  $('blindWords').innerHTML = (b.diff?.words || []).map((w) => {
    if (w.status === 'extra') {
      return `<span class="w bad">+${esc(w.heard)} <small>多唸</small></span>`;
    }
    const cls = w.status === 'correct' ? 'ok' : w.status === 'missing' ? 'bad' : 'warn';
    const icon = { correct: '✓', substituted: '音不對', missing: '沒聽到' }[w.status] || '?';
    const heard = w.heard && w.status === 'substituted' ? ` <small>→「${esc(w.heard)}」</small>` : '';
    return `<span class="w ${cls}">${esc(w.token)}${heard} <small>${icon}</small></span>`;
  }).join('');
  const diff = b.diff || {};
  const pct = Math.round((diff.rate || 0) * 100);
  $('blindScore').textContent = `盲聽逐字正確 ${diff.correct ?? 0}/${diff.total ?? 0}（${pct}%）`;
  $('blindMeta').textContent = `${b.latency_ms} ms · ${(b.cost_usd || 0).toFixed(5)} USD`;
}


function renderDecisions(d) {
  const card = $('decisionsCard');
  if (!d || !d.ok) {
    $('decP').textContent = '—';
    $('decBar').style.width = '0%';
    $('decLevel').textContent = '呼叫失敗：' + (d?.error || '未知錯誤');
    $('decLevels').innerHTML = '';
    $('decWords').innerHTML = '';
    $('decMeta').textContent = '';
    card.classList.add('failed');
    return;
  }
  card.classList.remove('failed');
  $('decP').textContent = (d.p_correct * 100).toFixed(0) + '%';
  $('decBar').style.width = Math.round(d.p_correct * 100) + '%';
  $('decLevel').textContent = `等級 ${d.level}/4 — ${d.level_label || ''}`;

  const labels = ['0 全錯', '1 多錯', '2 明顯錯', '3 小瑕疵', '4 很好'];
  $('decLevels').innerHTML = labels.map((lab, i) => {
    const p = d.level_probs?.[String(i)] ?? 0;
    const h = Math.max(3, Math.round(p * 40));
    const top = d.level === i ? 'top' : '';
    return `<div class="lb ${top}" title="${lab}: ${(p * 100).toFixed(1)}%">
      <i style="height:${h}px"></i><em>${i}</em></div>`;
  }).join('');

  $('decWords').innerHTML = (d.words || []).map((w) => {
    const cls = w.verdict === 'correct' ? 'ok' : w.verdict === 'wrong' ? 'warn' : 'bad';
    const label = w.verdict === 'correct' ? '✓' : w.verdict === 'wrong' ? '音錯' : '缺';
    const p = w.probs?.[w.verdict] != null ? Math.round(w.probs[w.verdict] * 100) + '%' : '';
    return `<span class="w ${cls}">${esc(w.token)} <small>${label} ${p}</small></span>`;
  }).join('');

  $('decMeta').textContent = `${d.latency_ms} ms · ${(d.cost_usd || 0).toFixed(5)} USD · ${d.usage?.total_input_tokens || '?'} tokens`;
}

function renderArgon(a) {
  const card = $('argonCard');
  if (!a || !a.ok) {
    $('argScore').textContent = '—';
    $('argBar').style.width = '0%';
    $('argSummary').textContent = '呼叫失敗：' + (a?.error || '未知錯誤');
    $('argTranscript').textContent = '—';
    $('argWords').innerHTML = '';
    $('argTips').innerHTML = '';
    $('argMeta').textContent = '';
    card.classList.add('failed');
    return;
  }
  card.classList.remove('failed');
  $('argScore').textContent = a.overall;
  $('argBar').style.width = Math.max(0, Math.min(100, a.overall)) + '%';
  $('argSummary').textContent = a.summary || '';
  $('argTranscript').textContent = a.transcript || '（沒有聽到語音）';

  $('argWords').innerHTML = (a.words || []).map((w) => {
    const cls = w.status === 'correct' ? 'ok' : w.status === 'mispronounced' ? 'warn'
      : w.status === 'missing' ? 'bad' : '';
    const icon = { correct: '✓', mispronounced: '音錯', missing: '缺', extra: '多' }[w.status] || '?';
    const heard = w.heard && w.status !== 'correct' && w.heard !== w.token
      ? ` <small>聽到「${esc(w.heard)}」</small>` : '';
    return `<span class="w ${cls}">${esc(w.token)}${heard} <small>${icon}</small></span>`;
  }).join('') + notesHtml(a.words);

  $('argTips').innerHTML = (a.tips || []).map((t) => `<p>${esc(t)}</p>`).join('');
  $('argMeta').textContent = `${a.latency_ms} ms · ${(a.cost_usd || 0).toFixed(5)} USD · `
    + `${a.usage?.totalTokenCount || a.usage?.total_input_tokens || '?'} tokens`;
}

function renderAgreement(ag) {
  const box = $('agreementBox');
  if (!ag || (!ag.decisions_vs_blind && !ag.argon_vs_blind)) { box.hidden = true; return; }
  box.hidden = false;
  const line = (label, o, aName, bName) => {
    if (!o) return '';
    return `${label}逐字判斷一致 <strong>${o.same}/${o.n}（${Math.round(o.rate * 100)}%）</strong>`;
  };
  $('agreementText').innerHTML = [
    line('Decisions 與盲聽：', ag.decisions_vs_blind),
    line('Argon 評分與盲聽：', ag.argon_vs_blind),
  ].filter(Boolean).join('<br>');
}


function notesHtml(words) {
  const items = (words || []).filter((w) => w.note);
  if (!items.length) return '';
  return '<ul class="notes">' + items.map((w) => (
    `<li><b>${esc(w.token)}</b>：${esc(w.note)}</li>`
  )).join('') + '</ul>';
}

/* ---------------- 回饋 ---------------- */
function resetFeedbackForm() {
  state.feedback = {};
  document.querySelectorAll('.seg button').forEach((b) => b.classList.remove('on'));
  $('fbNote').value = '';
  $('fbSaved').hidden = true;
  $('saveFeedback').disabled = false;
  $('feedbackBox').hidden = false;
}

async function saveFeedback() {
  if (!state.result) return;
  if (state.feedbackSaved) return;
  const note = $('fbNote').value.trim();
  if (!state.feedback.decisions_verdict && !state.feedback.argon_verdict
      && !state.feedback.blind_verdict && !note) {
    toast('請至少選一個判斷，或寫下備註');
    return;
  }
  const body = {
    record_id: state.result.record_id,
    decisions_verdict: state.feedback.decisions_verdict || null,
    argon_verdict: state.feedback.argon_verdict || null,
    blind_verdict: state.feedback.blind_verdict || null,
    child_reaction: state.feedback.child_reaction || null,
    note,
  };
  try {
    const res = await fetch('/api/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error((await res.json()).error || '儲存失敗');
    state.feedbackSaved = true;
    $('fbSaved').hidden = false;
    $('saveFeedback').disabled = true;
    toast('回饋已記錄，謝謝！');
  } catch (err) {
    toast('儲存失敗：' + (err.message || err));
  }
}

/* ---------------- 歷史 ---------------- */
async function toggleHistory() {
  const box = $('history');
  if (!box.hidden) { box.hidden = true; return; }
  box.hidden = false;
  box.scrollIntoView({ behavior: 'smooth', block: 'start' });
  const res = await fetch('/api/records?limit=100');
  const { records } = await res.json();
  const tbody = $('historyTable').querySelector('tbody');
  $('historyEmpty').hidden = records.length > 0;
  tbody.innerHTML = records.map((r) => {
    const d = r.result?.decisions || {};
    const a = r.result?.argon || {};
    const f = r.feedback || {};
    const pill = (v) => {
      const cls = v === 'accurate' ? 'good' : v === 'partial' ? 'mid' : v === 'inaccurate' ? 'bad' : '';
      const label = { accurate: '準', partial: '部分', inaccurate: '不準' }[v] || '—';
      return `<span class="pill ${cls}">${label}</span>`;
    };
    const short = (r.sentence || '').length > 34 ? r.sentence.slice(0, 34) + '…' : r.sentence;
    return `<tr>
      <td>${esc((r.created_at || '').slice(5, 16).replace('T', ' '))}</td>
      <td class="sentence-cell">${esc(short)}</td>
      <td>${esc({ child: '小朋友', teen: '青少年', adult: '大人' }[r.speaker] || '—')}</td>
      <td>${d.ok ? (d.p_correct * 100).toFixed(0) + '%' : '—'}</td>
      <td>${a.ok ? a.overall : '—'}</td>
      <td>D:${pill(f.decisions_verdict)} A:${pill(f.argon_verdict)} 盲:${pill(f.blind_verdict)}</td>
      <td><a href="/${r.audio_file}" target="_blank">▶</a></td>
    </tr>`;
  }).join('');
}

/* ---------------- 雜項 ---------------- */
async function refreshCost() {
  try {
    const res = await fetch('/api/stats');
    const s = await res.json();
    const txt = 'US$' + (s.cost_usd || 0).toFixed(4);
    $('costChip').textContent = txt;
    $('footCost').textContent = txt;
    if ((s.cost_usd || 0) > 5) $('costChip').style.color = '#b23a3a';
  } catch (_) { /* ignore */ }
}

function toast(msg) {
  const el = $('toast');
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(el._t);
  el._t = setTimeout(() => { el.hidden = true; }, 3200);
}

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

if (window.speechSynthesis) speechSynthesis.onvoiceschanged = () => {};
init();
