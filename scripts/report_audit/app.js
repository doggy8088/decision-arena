const D = __DATA__;
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const nf = (v) => Number(v).toLocaleString('en-US');

function fill(el, v) { if (el) el.innerHTML = v; }

/* ---------- 01 堆疊條 ---------- */
(function stack() {
  const order = [
    ['ok', '一致', 'var(--moss)'],
    ['tone', '只有聲調不同', 'var(--amber)'],
    ['syllable', '音節不同', 'var(--rust)'],
    ['nonstandard', '檔名非標準', 'var(--ink3)'],
    ['error', '呼叫失敗', 'var(--rule2)'],
  ];
  const total = order.reduce((a, [k]) => a + (D.dist[k] || 0), 0);
  $('#stack').innerHTML = order.filter(([k]) => D.dist[k]).map(([k, label, color]) => {
    const n = D.dist[k];
    const pct = n / total * 100;
    return `<div style="flex:${pct};background:${color}" title="${label}：${nf(n)}（${pct.toFixed(1)}%）">
      ${pct > 9 ? nf(n) : ''}</div>`;
  }).join('');
  $('#stackKey').innerHTML = order.filter(([k]) => D.dist[k]).map(([k, label, color]) =>
    `<span><i style="background:${color}"></i>${label}　<b class="num">${nf(D.dist[k])}</b>
      <span style="color:var(--ink3)">（${(D.dist[k] / total * 100).toFixed(1)}%）</span></span>`
  ).join('');
})();

/* ---------- 02 聲調列 ---------- */
(function toneRows() {
  $('#toneRows').innerHTML = D.tones.map((t) => {
    const cls = t.rate >= 70 ? '' : t.rate >= 50 ? 'mid' : 'low';
    const worst = t.worst ? `最常被聽成${t.worst.name}（${t.worst.n} 個）` : '—';
    return `<div class="tone-row">
      <div class="tl">${t.name}<small>${nf(t.n)} 個檔案</small></div>
      <div>
        <div class="tbar"><span class="${cls}" style="width:${t.rate}%"></span></div>
        <div class="tone-note">${worst}</div>
      </div>
      <div class="tp">${t.rate}%</div>
    </div>`;
  }).join('');
})();

/* ---------- 02 混淆矩陣 ---------- */
(function matrix() {
  const m = D.matrix;
  const max = Math.max(...m.flat());
  let html = '<div class="h"></div>';
  D.toneNames.forEach((n) => { html += `<div class="h">${n}</div>`; });
  m.forEach((row, i) => {
    html += `<div class="h row">${D.toneNames[i]}</div>`;
    row.forEach((v, j) => {
      const diag = i === j;
      const a = v ? 0.08 + (v / max) * 0.72 : 0;
      const bg = v ? (diag ? `rgba(47,111,94,${a})` : `rgba(168,67,26,${a})`) : 'transparent';
      const color = v && a > 0.45 ? '#fff' : 'inherit';
      html += `<div class="c ${diag ? 'diag' : ''} ${v ? '' : 'zero'}"
        style="background:${bg};color:${color}"
        title="檔名 ${D.toneNames[i]} → 模型 ${D.toneNames[j]}：${nf(v)} 個">${v || '·'}</div>`;
    });
  });
  $('#mx').innerHTML = html;
})();

/* ---------- 03 錯誤型態 ---------- */
(function types() {
  const max = Math.max(...D.types.map((t) => t.n));
  $('#typeRows').innerHTML = D.types.map((t) => `
    <div class="type-row">
      <div class="tn">${t.k}</div>
      <div class="tybar"><span style="width:${(t.n / max) * 100}%"></span></div>
      <div class="tv">${t.n}　<span style="color:var(--ink3)">${t.pct}%</span></div>
    </div>`).join('');
})();

(function pairs() {
  const tb = $('#pairTable tbody');
  tb.innerHTML = D.pairs.map((p) => `
    <tr><td class="mono">${p.a}</td><td class="mono">${p.b}</td>
    <td class="num" style="text-align:right">${p.n}</td></tr>`).join('');
})();

/* ---------- 04 仲裁 ---------- */
(function arb() {
  const { n, ok, bad } = D.arb;
  if (!n) { $('#split').innerHTML = '<div style="flex:1;background:var(--rule2)">沒有仲裁資料</div>'; return; }
  const a = ok / n * 100;
  $('#split').innerHTML = `
    <div style="flex:${a};background:var(--rust)">flash-lite 自己聽錯　${ok}（${a.toFixed(0)}%）</div>
    <div style="flex:${100 - a};background:var(--amber)">兩邊都說不對　${bad}（${(100 - a).toFixed(0)}%）</div>`;
  $('#splitKey').innerHTML = `
    <span><i style="background:var(--rust)"></i>Argon 與檔名相同 → 音檔沒問題，是 flash-lite 錯</span>
    <span><i style="background:var(--amber)"></i>Argon 也不同意檔名 → 音檔值得人工複查</span>`;

  $('#arbTable tbody').innerHTML = D.arb.rows.slice(0, 12).map((r) => `
    <tr>
      <td class="file">${r.f}</td>
      <td class="mono">${r.e}</td>
      <td class="mono">${r.f1}</td>
      <td class="mono">${r.f2}</td>
      <td><span class="tag ${r.who === 'flash-lite 錯' ? 'syllable' : 'tone'}">${r.who}</span></td>
    </tr>`).join('');
  $('#arbNote').textContent =
    `抽樣 ${n} 個；換算全量，flash-lite 標記的 ${nf(D.flags.length)} 個裡面約 ${nf(Math.round(D.flags.length * ok / n))} 個是它自己聽錯，約 ${nf(Math.round(D.flags.length * bad / n))} 個連 Argon 都覺得不對。`;
})();

/* ---------- 05 清單 ---------- */
const state = { q: '', status: 'all', voice: 'all', sort: 0, asc: true };
const TAGS = { tone: '聲調', syllable: '音節' };

function currentRows() {
  const q = state.q.trim().toLowerCase();
  let rows = D.flags;
  if (state.status !== 'all') rows = rows.filter((r) => r.s === state.status);
  if (state.voice !== 'all') rows = rows.filter((r) => r.v === state.voice);
  if (q) {
    rows = rows.filter((r) =>
      (r.v + '/' + r.n).toLowerCase().includes(q) ||
      r.e.toLowerCase().includes(q) || r.g.toLowerCase().includes(q));
  }
  const key = ['0', '1', '2', '3', '4'][state.sort];
  rows = rows.slice().sort((a, b) => {
    let x, y;
    if (state.sort === 3) { x = a.s; y = b.s; }
    else if (state.sort === 4) { x = a.a || 'zzz'; y = b.a || 'zzz'; }
    else { x = [a.v + '/' + a.n, a.e, a.g][state.sort]; y = [b.v + '/' + b.n, b.e, b.g][state.sort]; }
    return (x > y ? 1 : x < y ? -1 : 0) * (state.asc ? 1 : -1);
  });
  return rows;
}

function highlight(text, q) {
  if (!q) return text;
  const i = text.toLowerCase().indexOf(q);
  if (i < 0) return text;
  return `${text.slice(0, i)}<mark>${text.slice(i, i + q.length)}</mark>${text.slice(i + q.length)}`;
}

function renderTable() {
  const rows = currentRows();
  const q = state.q.trim().toLowerCase();
  const tbody = $('#flagTable tbody');
  tbody.innerHTML = rows.slice(0, 1200).map((r) => {
    const argon = r.as
      ? `<span class="tag ${r.as === 'ok' ? 'ok' : 'bad'}">${r.a}　${r.as === 'ok' ? '正確' : '也不對'}</span>`
      : '<span style="color:var(--ink3)">—</span>';
    return `<tr>
      <td class="file">${highlight(r.v + '/' + r.n, q)}</td>
      <td class="mono">${highlight(r.e, q)}</td>
      <td class="mono">${highlight(r.g, q)}</td>
      <td><span class="tag ${r.s}">${TAGS[r.s]}</span></td>
      <td>${argon}</td>
    </tr>`;
  }).join('');
  $('#flagCount').textContent = `顯示 ${nf(rows.length)} 筆 / 全部 ${nf(D.flags.length)} 筆`;
}

$('#q').addEventListener('input', (e) => { state.q = e.target.value; renderTable(); });
$('#fStatus').addEventListener('click', (e) => {
  const b = e.target.closest('button'); if (!b) return;
  state.status = b.dataset.v;
  $$('#fStatus button').forEach((x) => x.classList.toggle('on', x === b));
  renderTable();
});
$('#fVoice').addEventListener('click', (e) => {
  const b = e.target.closest('button'); if (!b) return;
  state.voice = b.dataset.v;
  $$('#fVoice button').forEach((x) => x.classList.toggle('on', x === b));
  renderTable();
});
$$('#flagTable thead th').forEach((th) => {
  th.addEventListener('click', () => {
    const s = Number(th.dataset.sort);
    state.asc = state.sort === s ? !state.asc : true;
    state.sort = s;
    renderTable();
  });
});

$('#dl').addEventListener('click', () => {
  const rows = currentRows();
  const head = 'voice,name,expected,heard,status,argon,argon_status\n';
  const body = rows.map((r) =>
    [r.v, r.n, r.e, r.g, r.s, r.a || '', r.as || ''].map((v) => `"${String(v).replace(/"/g, '""')}"`).join(',')
  ).join('\n');
  const blob = new Blob(['\ufeff' + head + body], { type: 'text/csv;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'flash-lite-audit-flags.csv';
  a.click();
  URL.revokeObjectURL(a.href);
});

renderTable();

/* ---------- 06 成本 ---------- */
(function cost() {
  const t = D.meta.tokens;
  const cText = t.text * 0.25 / 1e6;
  const cAudio = t.audio * 0.50 / 1e6;
  const cOut = t.out * 1.50 / 1e6;
  const total = cText + cAudio + cOut;
  fill($('#tkText'), nf(t.text)); fill($('#csText'), 'US$' + cText.toFixed(4));
  fill($('#tkAudio'), nf(t.audio)); fill($('#csAudio'), 'US$' + cAudio.toFixed(4));
  fill($('#tkOut'), nf(t.out)); fill($('#csOut'), 'US$' + cOut.toFixed(4));
  fill($('#tkAll'), nf(t.text + t.audio + t.out));
  fill($('#csAll'), 'US$' + total.toFixed(4));
  $$('[data-f="cost"]').forEach((el) => { el.textContent = total.toFixed(3); });
  fill($('#fTok'), nf(t.text + t.audio + t.out));
  fill($('#fCost'), total.toFixed(3));
})();

/* ---------- 主題 ---------- */
const root = document.documentElement;
function lsGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
function lsSet(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* ignore */ } }
const saved = lsGet('audit-theme');
if (saved) root.dataset.theme = saved;
const btn = $('#themeBtn');
function syncBtn() { btn.textContent = root.dataset.theme === 'dark' ? '淺色' : '深色'; }
syncBtn();
btn.addEventListener('click', () => {
  root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
  lsSet('audit-theme', root.dataset.theme);
  syncBtn();
});

/* ---------- 捲動 ---------- */
const prog = $('#prog');
const links = $$('#navlist a');
const secs = ['verdict', 'tone', 'syllable', 'who', 'list', 'cost', 'method']
  .map((id) => document.getElementById(id)).filter(Boolean);
function onScroll() {
  const h = document.documentElement;
  prog.style.width = (h.scrollTop / Math.max(1, h.scrollHeight - h.clientHeight) * 100) + '%';
  let cur = secs[0];
  secs.forEach((s) => { if (s.getBoundingClientRect().top <= 120) cur = s; });
  links.forEach((a) => a.classList.toggle('on', a.getAttribute('href') === '#' + cur.id));
}
window.addEventListener('scroll', onScroll, { passive: true });
onScroll();
