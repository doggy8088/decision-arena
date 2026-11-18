const D = __DATA__;
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const fmt = (n, d = 0) => (n === null || n === undefined) ? '—' : Number(n).toFixed(d);

/* ---------- data-f 填入 ---------- */
function pick(path) {
  return path.split('.').reduce((o, k) => (o == null ? o : o[k]), D);
}
$$('[data-f]').forEach((el) => {
  const v = pick(el.dataset.f);
  if (v !== undefined && v !== null) el.textContent = v;
});

/* ---------- tooltip ---------- */
const tip = $('#tip');
function showTip(html, ev) {
  tip.innerHTML = html;
  tip.style.opacity = '1';
  moveTip(ev);
}
function moveTip(ev) {
  const pad = 14;
  let x = ev.clientX + pad;
  let y = ev.clientY + pad;
  const r = tip.getBoundingClientRect();
  if (x + r.width > window.innerWidth - 8) x = ev.clientX - r.width - pad;
  if (y + r.height > window.innerHeight - 8) y = ev.clientY - r.height - pad;
  tip.style.left = x + 'px';
  tip.style.top = y + 'px';
}
function hideTip() { tip.style.opacity = '0'; }
document.addEventListener('mousemove', (e) => { if (tip.style.opacity === '1') moveTip(e); });

/* ---------- 01 能力長條 ---------- */
(function capBars() {
  const box = $('#capBars');
  box.innerHTML = D.cap.map((r) => `
    <div class="cap-row" data-cap='${JSON.stringify(r).replace(/'/g, '&#39;')}'>
      <div class="name">${r.label}<small>${r.sub || ''}</small></div>
      <div class="bars">
        <div class="bar d" data-tip="<b>Decisions</b> ${r.dnote || ''}">
          <span class="tag">D</span>
          <span class="track"><span class="fill" style="--w:${Math.min(100, r.d)}%"></span></span>
          <span class="val">${fmt(r.d)}%</span>
        </div>
        <div class="bar a" data-tip="<b>Argon</b> ${r.anote || ''}">
          <span class="tag">A</span>
          <span class="track"><span class="fill" style="--w:${Math.min(100, r.a)}%"></span></span>
          <span class="val">${fmt(r.a)}%</span>
        </div>
      </div>
    </div>`).join('');
  $$('[data-tip]').forEach((el) => {
    el.addEventListener('mouseenter', (e) => showTip(el.dataset.tip, e));
    el.addEventListener('mouseleave', hideTip);
  });
})();

/* ---------- 02 單音節點圖 ---------- */
(function strip() {
  const box = $('#strip');
  const lanes = [
    { key: true, label: '應為「是」', color: 'var(--good)' },
    { key: false, label: '應為「否」', color: 'var(--ink-3)' },
  ];
  box.innerHTML = lanes.map((ln) => {
    const dots = D.single.rows.filter((r) => r.expect === ln.key).map((r) => `
      <span class="dot" style="left:calc(${(r.p * 100).toFixed(1)}% );background:${ln.color}"
        data-tip="<b>${r.id}</b><br>P(ㄌㄨˊ) = ${r.p.toFixed(3)}<br>應該：${r.expect ? '是' : '否'}｜四選一：${r.top}"></span>`).join('');
    return `<div class="lane"><div class="lb">${ln.label}</div><div class="track">${dots}</div></div>`;
  }).join('');
  $$('.dot').forEach((el) => {
    el.addEventListener('mouseenter', (e) => showTip(el.dataset.tip, e));
    el.addEventListener('mouseleave', hideTip);
  });
})();

/* ---------- 03 混淆矩陣 ---------- */
let mxMode = 'd';
function renderMatrix() {
  const cats = D.scene.cats;
  const names = D.scene.catNames;
  const mx = mxMode === 'd' ? D.scene.matrixD : D.scene.matrixA;
  const max = Math.max(1, ...cats.map((t) => Math.max(...Object.values(mx[t] || {}), 1)));
  const score = mxMode === 'd' ? D.scene.accD : D.scene.accA;
  $('#mxScore').textContent = score;

  let html = '<div class="hdr"></div>';
  cats.forEach((c) => { html += `<div class="hdr" title="${names[c]}">${names[c]}</div>`; });
  cats.forEach((t) => {
    html += `<div class="hdr rowh" title="${names[t]}">${names[t]}</div>`;
    cats.forEach((p) => {
      const v = (mx[t] || {})[p] || 0;
      const diag = t === p;
      const alpha = v ? 0.14 + (v / max) * 0.62 : 0;
      const bg = diag
        ? `rgba(45,212,191,${alpha})`
        : (v ? `rgba(248,113,113,${alpha})` : 'transparent');
      html += `<div class="cell ${v ? '' : 'empty'} ${diag ? 'diag' : ''}"
        style="background:${bg}" data-t="${t}" data-p="${p}" data-v="${v}">${v || '·'}</div>`;
    });
  });
  const el = $('#mx');
  el.innerHTML = html;
  $$('.cell', el).forEach((c) => {
    c.addEventListener('click', () => showCell(c.dataset.t, c.dataset.p, Number(c.dataset.v)));
    c.addEventListener('mouseenter', (e) => {
      const names2 = D.scene.catNames;
      showTip(`<b>${names2[c.dataset.t]}</b> → ${names2[c.dataset.p]}<br>${c.dataset.v} 段`, e);
    });
    c.addEventListener('mouseleave', hideTip);
  });
  $('#mxDetail').innerHTML = mxMode === 'd'
    ? '點任何一格，看它把哪些片段放到那裡。'
    : '換成 Argon 的結果——它抓得到「演唱會」，但把三段座談會判成「單人說話」。';
}
function showCell(t, p, v) {
  const names = D.scene.catNames;
  const clips = D.scene.clips.filter((c) => c.cat === t && (mxMode === 'd' ? c.d : c.a) === p);
  const list = clips.length
    ? clips.map((c) => `<span class="pill ${t === p ? 'ok' : 'no'}" style="margin:3px 4px 3px 0">${c.id}</span>`).join('')
    : '<span style="color:var(--ink-3)">（沒有片段）</span>';
  $('#mxDetail').innerHTML = `<b>真實：${names[t]}</b> → 判成 <b>${names[p]}</b>，共 ${v} 段<br>
    <div style="margin-top:8px">${list}</div>`;
}
$('#mxToggle').addEventListener('click', (e) => {
  const b = e.target.closest('button');
  if (!b) return;
  mxMode = b.dataset.m;
  $$('#mxToggle button').forEach((x) => x.classList.toggle('on', x === b));
  renderMatrix();
});
renderMatrix();

/* ---------- 03 逐段清單 ---------- */
(function clipList() {
  const cats = D.scene.cats;
  const names = D.scene.catNames;
  const chips = ['all', ...cats];
  $('#clipChips').innerHTML = chips.map((c) => `
    <button class="chip ${c === 'all' ? 'on' : ''}" data-c="${c}">
      ${c === 'all' ? '全部 ' + D.scene.clips.length : names[c]}
    </button>`).join('');

  function draw(filter) {
    const list = D.scene.clips.filter((c) => filter === 'all' || c.cat === filter);
    $('#clipList').innerHTML = list.map((c) => `
      <div class="clip">
        <div class="cat">${names[c.cat]}</div>
        <div class="t" title="${c.title}">${c.id} · ${c.title}</div>
        <div class="pill ${c.okD ? 'ok' : 'no'}" title="Decisions：${names[c.d] || c.d}">D ${names[c.d] || c.d}</div>
        <div class="pill ${c.okA ? 'ok' : 'no'}" title="Argon：${names[c.a] || c.a}">A ${names[c.a] || c.a}</div>
      </div>`).join('');
  }
  $('#clipChips').addEventListener('click', (e) => {
    const b = e.target.closest('.chip');
    if (!b) return;
    $$('#clipChips .chip').forEach((x) => x.classList.toggle('on', x === b));
    draw(b.dataset.c);
  });
  draw('all');
})();

/* ---------- 04 變體長條 ---------- */
(function variantBars() {
  $('#varBars').innerHTML = D.pron.variants.map((v) => `
    <div class="vrow">
      <div class="n">${v.label}<small>${v.sub} · n=${v.n}</small></div>
      <div class="vbars">
        <div class="vbar p" data-tip="<b>Decisions</b> P=${(v.d / 100).toFixed(3)}">
          <span class="tr"><span class="fl" style="--w:${Math.min(100, v.d)}%"></span></span>
          <span class="num">${fmt(v.d)}</span>
        </div>
        <div class="vbar q" data-tip="<b>Argon</b> ${fmt(v.a)} / 100">
          <span class="tr"><span class="fl" style="--w:${Math.min(100, v.a)}%"></span></span>
          <span class="num">${fmt(v.a)}</span>
        </div>
      </div>
    </div>`).join('');
  $$('[data-tip]').forEach((el) => {
    if (el.__bound) return;
    el.__bound = 1;
    el.addEventListener('mouseenter', (e) => showTip(el.dataset.tip, e));
    el.addEventListener('mouseleave', hideTip);
  });
})();

/* ---------- 04 陷阱 tabs ---------- */
$('#trapTabs').addEventListener('click', (e) => {
  const b = e.target.closest('.tab');
  if (!b) return;
  $$('#trapTabs .tab').forEach((x) => x.classList.toggle('on', x === b));
  $$('.trap').forEach((t) => t.classList.toggle('on', t.dataset.trap === b.dataset.t));
});

/* ---------- 05 選型指南 ---------- */
const GUIDE = [
  {
    key: 'gate', label: '偵測有沒有人聲', sub: '呼叫中心、語音入口的守門員',
    verdict: '用 Decisions', color: 'var(--good)',
    why: '只要判斷「這段要不要進入下一步」，兩個模型都是 42/42 全對。但 Decisions 快 13 倍、便宜 26 倍，而且輸出就是可以直接當門檻用的機率。',
    pills: [['42/42', 'ok'], ['500 ms', 'ok'], ['US$0.00009／次', 'ok']],
    stats: [['準確率', '100%'], ['延遲', '0.5 s']],
  },
  {
    key: 'scene', label: '分辨錄音場合', sub: '現場 / 錄音室 / 戶外',
    verdict: '不要用 Decisions', color: 'var(--bad)',
    why: '演唱會 6 段全部被判成「唱歌」。它抓得到內容（有人在唱），但抓不到「在哪裡錄的」。這類判斷請用 Argon（5/6），或自己在音訊特徵上做。',
    pills: [['Decisions 0/6', 'no'], ['Argon 5/6', 'ok']],
    stats: [['演唱會召回', '0%'], ['誤判方向', '→ 唱歌']],
  },
  {
    key: 'count', label: '判斷有幾個人在講', sub: '與會者計數、發言人切換',
    verdict: '兩邊都不夠', color: 'var(--acc-2)',
    why: 'Decisions 4/6、Argon 3/6。但要留意：10 秒窗內常常真的只有一個人在說話，所以這是「任務本身太難」，不是單純模型爛。要真的做人數，需要更長的音訊或 diarization。',
    pills: [['D 4/6', 'no'], ['A 3/6', 'no']],
    stats: [['Decisions', '67%'], ['Argon', '50%']],
  },
  {
    key: 'pron', label: '檢查發音對不對', sub: '語言學習、朗讀練習',
    verdict: 'Argon 可用，但要修三個坑', color: 'var(--acc-2)',
    why: 'Argon 分得出「唸成完全不同的句子」（1.5 分）與「正確」（99.1 分），逐字抓錯 24/34。但中文聲調錯幾乎抓不到（平均 93.4 分），而且總分會浮動——要看逐字標記，不要看總分。Decisions 的逐字抓錯是 0/34。',
    pills: [['句子層級 0.94 AUC', 'ok'], ['逐字 24/34', 'ok'], ['聲調 3/5 漏抓', 'no']],
    stats: [['Argon AUC', '0.94'], ['Decisions AUC', '0.70']],
  },
  {
    key: 'phoneme', label: '判斷單一音節的聲調', sub: '注音教材、逐字發音驗收',
    verdict: '不要用 Decisions', color: 'var(--bad)',
    why: '正確的「爐」拿 0.611，毫不相干的「水」拿 0.780——分數完全沒有鑑別力，四選一 0/2。同一件事交給 Argon 是 12/12，但要 2–3 次取樣投票，單次會出現假警報。',
    pills: [['Decisions 0/2', 'no'], ['Argon 12/12', 'ok']],
    stats: [['正例平均 P', '0.66'], ['負例平均 P', '0.64']],
  },
];
(function guide() {
  $('#glist').innerHTML = GUIDE.map((g, i) => `
    <button class="gitem ${i === 0 ? 'on' : ''}" data-k="${g.key}">${g.label}<small>${g.sub}</small></button>`).join('');
  function draw(key) {
    const g = GUIDE.find((x) => x.key === key) || GUIDE[0];
    $('#gpanel').innerHTML = `
      <div style="font-size:12px;color:var(--ink-3);letter-spacing:.08em">${g.sub}</div>
      <div class="verdict" style="color:${g.color}">${g.verdict}</div>
      <div class="why">${g.why}</div>
      <div class="gpills">${g.pills.map((p) => `<span class="pill ${p[1]}">${p[0]}</span>`).join('')}</div>
      <div class="gstat">${g.stats.map((s) => `<div>${s[0]}<b>${s[1]}</b></div>`).join('')}</div>`;
  }
  $('#glist').addEventListener('click', (e) => {
    const b = e.target.closest('.gitem');
    if (!b) return;
    $$('.gitem').forEach((x) => x.classList.toggle('on', x === b));
    draw(b.dataset.k);
  });
  draw(GUIDE[0].key);
})();

/* ---------- 主題切換 ---------- */
const root = document.documentElement;
// file:// 底下 localStorage 可能丟 SecurityError，一律包起來
function lsGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
function lsSet(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* ignore */ } }
const saved = lsGet('rep-theme');
if (saved) root.dataset.theme = saved;
const themeBtn = $('#themeBtn');
function syncTheme() {
  themeBtn.textContent = root.dataset.theme === 'dark' ? '☾ 深色' : '☀ 淺色';
}
syncTheme();
themeBtn.addEventListener('click', () => {
  root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
  lsSet('rep-theme', root.dataset.theme);
  syncTheme();
  renderMatrix();
});

/* ---------- 捲動：進度、導覽、reveal、長條動畫 ---------- */
const prog = $('#prog');
const navLinks = $$('#navlist a');
const sections = ['map', 's1', 's2', 's3', 'guide', 'cost', 'limits']
  .map((id) => document.getElementById(id)).filter(Boolean);

function onScroll() {
  const h = document.documentElement;
  const p = h.scrollTop / Math.max(1, h.scrollHeight - h.clientHeight);
  prog.style.width = (p * 100).toFixed(1) + '%';
  let cur = sections[0];
  sections.forEach((s) => { if (s.getBoundingClientRect().top <= 140) cur = s; });
  navLinks.forEach((a) => a.classList.toggle('on', a.getAttribute('href') === '#' + cur.id));
}
window.addEventListener('scroll', onScroll, { passive: true });
onScroll();

// 進場動畫：不用 IntersectionObserver（headless / 舊瀏覽器都可能不動作），
// 改成「進視窗就開」，並保證任何情況下內容一定看得到。
const pending = $$('.reveal');
pending.forEach((el) => {
  const r = el.getBoundingClientRect();
  if (r.top < window.innerHeight * 0.95) el.classList.add('reveal-live');
  else el.classList.add('anim');
});

let pendingLeft = pending.filter((el) => el.classList.contains('anim'));
function revealPass() {
  if (!pendingLeft.length) return;
  const keep = [];
  pendingLeft.forEach((el) => {
    if (el.getBoundingClientRect().top < window.innerHeight * 0.95) {
      el.classList.add('in');
    } else keep.push(el);
  });
  pendingLeft = keep;
}
window.addEventListener('scroll', revealPass, { passive: true });
revealPass();

// 保險：3 秒後仍在畫面上方的就直接顯示（避免任何情況白畫面）
setTimeout(() => {
  pendingLeft.forEach((el) => {
    if (el.getBoundingClientRect().top < window.innerHeight * 1.2) {
      el.classList.add('in');
    }
  });
}, 3000);
