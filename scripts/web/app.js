(() => {
'use strict';
const D = window.CT;
const N = D.nodes, C = D.concepts, W = D.words, SH = D.shlokas, DH = D.dhatus, UP = D.upas, EX = D.examples;
// W row: [word, linga, sankhya, artha, id, sudha_id, [ks_id...]]
// EX row: [conceptIdx|-1, word, vakya, src, notes, notes2, file]

// ---------------------------------------------------------------- helpers
function h(tag, cls, ...kids){
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  for (const k of kids) if (k != null && k !== false) e.append(k instanceof Node ? k : String(k));
  return e;
}
function link(text, fn, title){
  const b = h('button', 'lnk', text);
  if (title) b.title = title;
  b.onclick = e => { e.stopPropagation(); fn(); };
  return b;
}
function group(arr, keyFn){
  const m = new Map();
  arr.forEach((x, i) => { for (const k of [].concat(keyFn(x))) { if (k === '' || k == null) continue; if (!m.has(k)) m.set(k, []); m.get(k).push(i); } });
  return m;
}
const store = {
  get(k, d){ try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch { return d; } },
  set(k, v){ try { localStorage.setItem(k, JSON.stringify(v)); } catch {} }
};

// ---------------------------------------------------------------- indices
const nodeByPath = new Map(N.map((n, i) => [n.p, i]));
const conceptById = new Map(C.map((c, k) => [c.id, k]));
const akConcepts = new Map(), dpConcepts = new Map(), scConcepts = new Map();
C.forEach((c, k) => c.ar.forEach(([s, a]) => {
  const m = s === 'ak' ? akConcepts : s === 'dp' ? dpConcepts : scConcepts;
  if (!m.has(a)) m.set(a, []); m.get(a).push(k);
}));
const rowsByArtha = group(W, r => r[3]);
const rowsByWord = group(W, r => r[0]);
const rowsBySankhya = group(W, r => r[2]);
const sankhyas = [...rowsBySankhya.keys()];
const sankhyaPos = new Map(sankhyas.map((s, i) => [s, i]));
const rowById = new Map(W.map((r, i) => [r[4], i]));
const dhatuById = new Map(DH.map((d, i) => [d.id, i]));
const upaByKey = new Map(UP.map((u, i) => [u.key, i]));
const dhatusByStem = group(DH, d => d.ar);
const upasByStem = group(UP, u => u.ar);
const upasByBase = group(UP, u => u.b);
const exByWord = group(EX, e => e[1]);

function pathParts(ni){ const out = []; for (let i = ni; i >= 0; i = N[i].pi) out.unshift(i); return out; }
function pathText(ni){ return pathParts(ni).map(i => N[i].n).join(' › '); }
function conceptsOf(src, a){ return (src === 'ak' ? akConcepts : src === 'dp' ? dpConcepts : scConcepts).get(a) || []; }

// ---------------------------------------------------------------- tree
const treeEl = document.getElementById('tree');
const nodeEl = {}, conceptEl = {};

function expandable(cls, fillRow, buildBody, hasBody, onRow){
  const wrap = h('div', cls), row = h('div', 'row ' + cls.split(' ')[0] + '-row');
  const caret = h('span', 'caret', hasBody ? '▸' : '·');
  row.append(caret); fillRow(row);
  const body = h('div', 'kids'); body.hidden = true;
  wrap.append(row, body);
  let built = false;
  wrap._open = open => {
    if (!hasBody) return;
    if (open && !built){ buildBody(body); built = true; }
    body.hidden = !open; caret.textContent = open ? '▾' : '▸';
  };
  wrap._row = row;
  row.onclick = () => { wrap._open(body.hidden); if (onRow) onRow(); };
  return wrap;
}

// make tree paths inside free text clickable (not_this, definitions)
const pathRe = (() => {
  const ps = N.map(n => n.p).sort((a, b) => b.length - a.length).map(p => p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  return new RegExp('(?<=^|[\\s(→,;])(' + ps.join('|') + ')(?=$|[\\s),;.])', 'g');
})();
function linkPaths(text){
  const frag = document.createDocumentFragment();
  let last = 0;
  for (const m of text.matchAll(pathRe)){
    frag.append(text.slice(last, m.index));
    const i = nodeByPath.get(m[1]);
    frag.append(link(m[1], () => revealNode(i), 'Show in tree'));
    last = m.index + m[1].length;
  }
  frag.append(text.slice(last));
  return frag;
}

function makeNode(i){
  const n = N[i];
  const depth = pathParts(i).length - 1;
  const w = expandable('node lvl' + Math.min(depth, 3) + (n.m ? ' missing' : ''), row => {
    row.append(h('span', 'name', n.n));
    if (n.t) row.append(h('span', 'badge', n.t));
    if (n.d){ const d = h('span', 'def', n.d); d.title = n.d; row.append(d); }
  }, body => {
    if (n.m) body.append(h('div', 'info warn', 'Used by concepts but not in tree.csv.'));
    const info = h('div', 'info');
    if (n.a) info.append(h('div', null, h('b', null, 'anchors: '), n.a));
    if (n.x && n.x !== '—') info.append(h('div', null, h('b', null, 'not this: '), linkPaths(n.x)));
    if (info.childNodes.length) body.append(info);
    n.c.forEach(c => body.append(makeNode(c)));
    n.k.forEach(k => body.append(makeConcept(k)));
  }, n.c.length + n.k.length > 0 || n.m, () => show({t: 'n', k: n.p}, false));
  nodeEl[i] = w;
  return w;
}

function makeConcept(k){
  const c = C[k];
  const w = expandable('concept', row => {
    row.append(h('span', 'name', c.id));
    row.append(h('span', 'badge', c.ar.length + (c.ar.length === 1 ? ' artha' : ' arthas')));
    if (c.ex.length) row.append(h('span', 'exb', '✎ ' + c.ex.length));
    if (c.cf) row.append(h('span', 'tag t-mut', c.cf));
  }, body => {
    body.append(h('div', 'pathline', pathText(c.ni)));
    w._arthas = c.ar.map(([s, a]) => { const x = makeArtha(s, a); body.append(x); return x; });
  }, true, () => show({t: 'c', k: c.id}, false));
  conceptEl[k] = w;
  return w;
}

function arthaCount(src, a){
  if (src === 'ak'){ const n = uniqueWordRows(a).length; return n ? n + (n === 1 ? ' word' : ' words') : 'not found'; }
  if (src === 'dp'){ const n = (dhatusByStem.get(a) || []).length + (upasByStem.get(a) || []).length; return n ? n + (n === 1 ? ' dhātu' : ' dhātus') : 'not found'; }
  return '';
}
function makeArtha(src, a){
  return expandable('artha', row => {
    row.append(h('span', 'tag t-' + src, src), h('span', 'name', a));
    const n = arthaCount(src, a); if (n) row.append(h('span', 'badge', n));
  }, body => body.append(arthaChips(src, a)), src === 'ak' || src === 'dp');
}

function uniqueWordRows(a){
  const seen = new Set(), out = [];
  for (const i of rowsByArtha.get(a) || []) if (!seen.has(W[i][0])){ seen.add(W[i][0]); out.push(i); }
  return out;
}
function wordChip(i, cur){
  const b = h('button', 'chip' + (i === cur ? ' on' : ''), W[i][0]);
  b.title = W[i][2] + ' · ' + W[i][3];
  b.onclick = e => { e.stopPropagation(); show({t: 'w', k: W[i][4]}); };
  return b;
}
function dhatuChip(di){
  const d = DH[di];
  const b = h('button', 'chip', d.au || d.d, h('small', null, d.id));
  b.title = (d.raw || '') + (d.hi ? ' · ' + d.hi : '');
  b.onclick = e => { e.stopPropagation(); show({t: 'd', k: d.id}); };
  return b;
}
function upaChip(ui){
  const u = UP[ui];
  const b = h('button', 'chip', u.f, h('small', null, u.u + '+' + (u.bd || '')));
  b.title = (u.raw || '') + (u.hi ? ' · ' + u.hi : '');
  b.onclick = e => { e.stopPropagation(); show({t: 'u', k: u.key}); };
  return b;
}
function arthaChips(src, a){
  const frag = document.createDocumentFragment();
  if (src === 'ak'){
    const rows = uniqueWordRows(a);
    if (!rows.length){ frag.append(h('div', 'info warn', 'No Amarakosha row has this अर्थः.')); return frag; }
    frag.append(h('div', 'chips', ...rows.map(i => wordChip(i))));
  } else if (src === 'dp'){
    const ds = dhatusByStem.get(a) || [], us = upasByStem.get(a) || [];
    if (!ds.length && !us.length){ frag.append(h('div', 'info warn', 'No dhātu or upasarga row has this artha.')); return frag; }
    if (ds.length) frag.append(h('div', 'grp', 'dhātus (' + ds.length + ')'), h('div', 'chips', ...ds.map(dhatuChip)));
    if (us.length) frag.append(h('div', 'grp', 'with upasarga (' + us.length + ')'), h('div', 'chips', ...us.map(upaChip)));
  }
  return frag;
}

N.forEach((n, i) => { if (n.pi === -1) treeEl.append(makeNode(i)); });

function openNode(i){ if (N[i].pi >= 0) openNode(N[i].pi); nodeEl[i]._open(true); }
function flash(w){
  w.classList.remove('flash'); void w.offsetWidth; w.classList.add('flash');
  w._row.scrollIntoView({block: 'center', behavior: 'smooth'});
}
function revealNode(i){ if (N[i].pi >= 0) openNode(N[i].pi); flash(nodeEl[i]); }
let curRow = null;
function revealConcept(k, artha){
  openNode(C[k].ni);
  const w = conceptEl[k]; w._open(true);
  if (curRow) curRow.classList.remove('cur');
  curRow = w._row; curRow.classList.add('cur');
  let target = w;
  if (artha){ const j = C[k].ar.findIndex(x => x[0] === artha[0] && x[1] === artha[1]); if (j >= 0){ target = w._arthas[j]; target._open(true); } }
  flash(target);
}

// ---------------------------------------------------------------- panel / cards
const panel = document.getElementById('panel'), cardEl = document.getElementById('card'), recentEl = document.getElementById('recent');
document.getElementById('closepanel').onclick = () => document.body.classList.remove('panel-open');

function keyOf(d){ return d.t + '=' + encodeURIComponent(d.k); }
function parseHash(){
  const m = location.hash.match(/^#([cwdun])=(.+)$/);
  return m ? {t: m[1], k: decodeURIComponent(m[2])} : null;
}
let current = null;
function show(d, reveal = true){
  const key = keyOf(d);
  if (location.hash.slice(1) !== key) history.pushState(null, '', '#' + key);
  render(d, reveal);
}
window.addEventListener('popstate', () => { const d = parseHash(); if (d) render(d, true); });

function render(d, reveal){
  const fn = {c: cardConcept, w: cardWord, d: cardDhatu, u: cardUpa, n: cardNode}[d.t];
  const card = fn && fn(d.k);
  if (!card) return;
  current = d;
  cardEl.replaceChildren(card);
  panel.scrollTop = 0;
  document.body.classList.add('panel-open');
  remember(d, card._label);
  if (reveal && card._reveal) card._reveal();
}

let recent = store.get('ct.recent', []);
function remember(d, label){
  recent = recent.filter(r => !(r.t === d.t && r.k === d.k));
  recent.unshift({t: d.t, k: d.k, l: label});
  recent = recent.slice(0, 10);
  store.set('ct.recent', recent);
  drawRecent();
}
function drawRecent(){
  recentEl.replaceChildren();
  const items = recent.filter(r => !(current && r.t === current.t && r.k === current.k)).slice(0, 8);
  if (!items.length) return;
  recentEl.append(h('span', 'lbl', 'Recent:'));
  items.forEach(r => { const b = h('button', null, r.l); b.onclick = () => show(r); recentEl.append(b); });
}

function crumbs(ni){
  const c = h('div', 'crumbs');
  pathParts(ni).forEach((i, j) => { if (j) c.append(' › '); c.append(link(N[i].n, () => revealNode(i), 'Show in tree')); });
  return c;
}
function conceptLinks(src, a, withPath = true){
  const ks = conceptsOf(src, a);
  if (!ks.length) return [h('span', 'p warn', 'not in artha_map')];
  return ks.map(k => {
    const s = h('span', null, link('◆ ' + C[k].id, () => show({t: 'c', k: C[k].id})));
    if (withPath) s.append(' ', h('span', 'p', pathText(C[k].ni)));
    return s;
  });
}
function leafInfo(ni){
  const n = N[ni], box = h('div', 'leafinfo');
  if (n.d) box.append(h('div', 'ldef', n.d));
  if (n.a) box.append(h('div', null, h('b', null, 'anchors: '), n.a));
  if (n.x && n.x !== '—') box.append(h('div', null, h('b', null, 'not this: '), linkPaths(n.x)));
  return box.childNodes.length ? box : null;
}
function cardNode(path){
  const i = nodeByPath.get(path); if (i == null) return null;
  const n = N[i], card = h('div', 'card');
  if (n.pi >= 0) card.append(crumbs(n.pi));
  card.append(h('h2', null, n.n, h('small', null, n.t + ' concepts')));
  const info = leafInfo(i); if (info) card.append(info);
  if (n.c.length) card.append(section('Branches (' + n.c.length + ')', h('div', 'chips', ...n.c.map(c => {
    const b = h('button', 'chip', N[c].n, h('small', null, N[c].t)); b.title = N[c].d;
    b.onclick = () => { show({t: 'n', k: N[c].p}); }; return b; }))));
  if (n.k.length) card.append(section('Concepts (' + n.k.length + ')', h('div', 'chips', ...n.k.map(k => {
    const b = h('button', 'chip', C[k].id, C[k].ex.length ? h('small', null, '✎' + C[k].ex.length) : null);
    b.onclick = () => show({t: 'c', k: C[k].id}); return b; }))));
  card._label = n.n;
  card._reveal = () => revealNode(i);
  return card;
}
function section(title, ...kids){ return h('section', null, h('h3', null, title), ...kids); }

// ---- concept
function cardConcept(id){
  const k = conceptById.get(id); if (k == null) return null;
  const c = C[k];
  const card = h('div', 'card');
  card.append(crumbs(c.ni));
  const t = h('h2', null, '◆ ' + c.id);
  const li = leafInfo(c.ni);
  if (c.cf) t.append(h('span', 'tag t-mut', c.cf));
  card.append(t);
  if (li) card.append(li);
  if (c.nt) card.append(h('div', 'note', c.nt));
  if (c.mf.length) card.append(h('div', 'note', 'also includes (merged): ' + c.mf.join(', ')));
  const ar = c.ar.map(([s, a]) => {
    const n = arthaCount(s, a);
    return h('div', 'arow', h('div', 'head', h('span', 'tag t-' + s, s), h('b', null, a), n ? h('span', 'badge', n) : null), arthaChips(s, a));
  });
  card.append(section('Arthas', ...(ar.length ? ar : [h('div', 'empty', 'No arthas mapped yet.')])));
  if (c.ex.length) card.append(section('Examples (' + c.ex.length + ')', ...c.ex.map(e => exampleBlock(e, true))));
  card._label = '◆ ' + c.id;
  card._reveal = () => revealConcept(k);
  return card;
}

// ---- Amarakosha word
function cardWord(id){
  const i = rowById.get(id); if (i == null) return null;
  const r = W[i], [word, linga, sankhya, artha] = r;
  const card = h('div', 'card');
  const ks = akConcepts.get(artha) || [];
  if (ks.length) card.append(crumbs(C[ks[0]].ni));
  card.append(h('h2', null, word, h('small', null, [linga, r[4]].filter(Boolean).join(' · '))));

  const senses = rowsByWord.get(word) || [];
  const senseLine = j => {
    const s = h('div', 'sense' + (j === i ? ' cur' : ''));
    s.append(h('span', 'tag t-ak', 'ak'));
    s.append(j === i ? h('b', null, W[j][3]) : link(W[j][3], () => show({t: 'w', k: W[j][4]}), 'Open this sense'));
    s.append(h('span', 'p', W[j][2]), ...conceptLinks('ak', W[j][3]));
    return s;
  };
  card.append(section(senses.length > 1 ? 'Senses of ' + word + ' (' + senses.length + ')' : 'Sense', ...senses.map(senseLine)));

  const exs = exByWord.get(word) || [];
  if (exs.length) card.append(section('Examples (' + exs.length + ')', ...exs.map(e => exampleBlock(e, false))));

  card.append(section('Shloka', verseStrip(sankhya, i)));

  const comm = h('div', null, h('div', 'empty', 'Loading commentaries…'));
  card.append(section('Commentary', comm));
  loadComm(() => fillComm(comm, r));

  card._label = word + ' · ' + artha;
  card._reveal = () => { if (ks.length) revealConcept(ks[0], ['ak', artha]); };
  return card;
}

function verseStrip(sankhya, curRow){
  const box = h('div', 'verse');
  const draw = s => {
    box.replaceChildren();
    const pos = sankhyaPos.get(s);
    const prev = h('button', null, '‹ prev'), next = h('button', null, 'next ›');
    prev.disabled = !(pos > 0); next.disabled = !(pos < sankhyas.length - 1);
    prev.onclick = () => draw(sankhyas[pos - 1]); next.onclick = () => draw(sankhyas[pos + 1]);
    box.append(h('div', 'nav', prev, h('span', null, s), next));
    if (s.startsWith('3.03')) box.append(h('div', 'nanartha', 'नानार्थवर्ग: neighbours here share an ending, not a meaning.'));
    box.append(h('div', 'txt', SH[s] || '(shloka not found)'));
    // consecutive rows with the same artha form one group
    const rows = rowsBySankhya.get(s) || [];
    let g = null;
    for (const j of rows){
      if (!g || W[j][3] !== g.a){ g = {a: W[j][3], rows: []}; drawGroup(g); }
      g.rows.push(j); g.chips.append(wordChip(j, curRow));
    }
    function drawGroup(g){
      const ks = akConcepts.get(g.a) || [];
      const lab = h('span', 'lab', ks.length ? link(g.a, () => show({t: 'c', k: C[ks[0]].id}), pathText(C[ks[0]].ni)) : h('span', null, g.a));
      if (ks.length){ const lf = h('span', 'leaf', N[C[ks[0]].ni].n); lf.title = pathText(C[ks[0]].ni); lab.append(lf); }
      g.chips = h('div', 'chips');
      box.append(h('div', 'vg', lab, g.chips));
    }
  };
  draw(sankhya);
  return box;
}

let commState = 0; const commWait = [];
function loadComm(cb){
  if (window.CT_COMM) return cb();
  commWait.push(cb);
  if (commState) return;
  commState = 1;
  const s = document.createElement('script');
  s.src = window.CT_COMM_URL || 'data/comm.js';
  s.onload = () => commWait.splice(0).forEach(f => f());
  s.onerror = () => { commState = 0; commWait.splice(0).forEach(f => f()); };
  document.head.append(s);
}
function fillComm(box, r){
  box.replaceChildren();
  const CM = window.CT_COMM;
  if (!CM){ box.append(h('div', 'empty', 'Could not load commentaries.')); return; }
  const add = (title, entries) => {
    if (!entries.length) return;
    const d = h('details', 'comm'); d.open = true;
    d.append(h('summary', null, title));
    entries.forEach(([w, t]) => d.append(h('div', 'body', h('span', 'w', w + ' — '), t)));
    box.append(d);
  };
  add('सुधा', r[5] && CM.s[r[5]] ? [CM.s[r[5]]] : []);
  add('क्षीरस्वामी', r[6].map(x => CM.k[x]).filter(Boolean));
  if (!box.childNodes.length) box.append(h('div', 'empty', 'No commentary linked to this word.'));
}

// ---- examples
function highlight(v, w){
  const frag = document.createDocumentFragment();
  if (!w){ frag.append(v); return frag; }
  const cp = s => [...s];
  const wc = cp(w).filter(ch => ch !== 'ः' && ch !== 'ं');
  let best = null, bestLen = 0;
  for (const m of v.matchAll(/[^\s।॥,;.!?'"‘’“”()\-–—]+/g)){
    const tc = cp(m[0]); let n = 0;
    while (n < tc.length && n < wc.length && tc[n] === wc[n]) n++;
    if (n > bestLen){ bestLen = n; best = m; }
  }
  if (!best || bestLen < Math.min(4, wc.length) || bestLen < wc.length * 0.5){ frag.append(v); return frag; }
  frag.append(v.slice(0, best.index), h('mark', null, best[0]), v.slice(best.index + best[0].length));
  return frag;
}
function exampleBlock(e, showWord){
  const [k, w, v, src, n1, n2, file] = EX[e];
  const b = h('div', 'ex', h('div', 'v', highlight(v, w)));
  const s = h('div', 'src', [src, file].filter(Boolean).join(' · '));
  if (showWord && w){
    const rows = rowsByWord.get(w);
    s.prepend(rows ? link(w, () => show({t: 'w', k: W[rows[0]][4]})) : w, ' · ');
  }
  if (!showWord && k >= 0) s.prepend(link('◆ ' + C[k].id, () => show({t: 'c', k: C[k].id})), ' · ');
  b.append(s);
  if (n1) b.append(h('div', 'n', n1));
  if (n2) b.append(h('div', 'n2', n2));
  return b;
}

// ---- dhatu / upasarga
function stemLines(stems){
  if (!stems.length) return [h('div', 'empty', 'No arthas.')];
  return stems.map(a => h('div', 'sense', h('span', 'tag t-dp', 'dp'), h('b', null, a), ...conceptLinks('dp', a)));
}
function cardDhatu(id){
  const i = dhatuById.get(id); if (i == null) return null;
  const d = DH[i];
  const card = h('div', 'card');
  card.append(h('h2', null, d.au || d.d, h('small', null, [d.d !== d.au ? d.d : '', d.id].filter(Boolean).join(' · '))));
  card.append(h('div', 'meta', [d.gn && d.gn + (d.gi ? ' (' + d.gi + ')' : ''), d.pd, d.st, d.km, d.cm].filter(Boolean).join(' · ')));
  if (d.raw || d.hi) card.append(h('div', 'note', [d.raw, d.hi].filter(Boolean).join(' — ')));
  if (d.nt) card.append(h('div', 'note', d.nt));
  card.append(section('Arthas', ...stemLines(d.ar)));
  const us = upasByBase.get(d.id) || [];
  if (us.length) card.append(section('With upasarga (' + us.length + ')', h('div', 'chips', ...us.map(upaChip))));
  card._label = d.au || d.d;
  card._reveal = () => { const ks = d.ar.flatMap(a => dpConcepts.get(a) || []); if (ks.length) revealConcept(ks[0], ['dp', d.ar.find(a => dpConcepts.has(a))]); };
  return card;
}
function cardUpa(key){
  const i = upaByKey.get(key); if (i == null) return null;
  const u = UP[i];
  const card = h('div', 'card');
  card.append(h('h2', null, u.f, h('small', null, u.u + ' + ' + (u.bd || ''))));
  const bi = dhatuById.get(u.b);
  const meta = h('div', 'meta', 'base: ');
  meta.append(bi != null ? dhatuChip(bi) : u.b);
  if (u.fl) meta.append(' · ', h('span', 'warn', u.fl));
  card.append(meta);
  if (u.raw || u.hi) card.append(h('div', 'note', [u.raw.split(';').join('; '), u.hi].filter(Boolean).join(' — ')));
  if (u.nt) card.append(h('div', 'note', u.nt));
  card.append(section('Arthas', ...stemLines(u.ar)));
  card._label = u.f;
  card._reveal = () => { const a = u.ar.find(x => dpConcepts.has(x)); if (a) revealConcept(dpConcepts.get(a)[0], ['dp', a]); };
  return card;
}

function helpCard(){
  const card = h('div', 'card help');
  card.append(h('h2', null, 'Concept Tree'));
  card.append(h('p', null, 'Open a branch on the left and click a concept, an Amarakosha word or a dhātu to see its details here: every sense of a word, its shloka with the neighbouring synsets, the commentaries, and your examples.'));
  card.append(h('p', null, N.length + ' nodes · ' + C.length + ' concepts · ' + W.length + ' Amarakosha rows · ' + DH.length + ' dhātus · ' + UP.length + ' upasarga forms · ' + EX.length + ' examples'));
  return card;
}

// ---------------------------------------------------------------- search
let IDX = null;
function buildIndex(){
  IDX = [];
  N.forEach((n, i) => IDX.push({l: n.n, kind: 'node', s: n.p, go: () => revealNode(i)}));
  C.forEach((c, k) => {
    IDX.push({l: c.id, kind: 'concept', s: pathText(c.ni), go: () => show({t: 'c', k: c.id})});
    c.ar.forEach(([s, a]) => IDX.push({l: a, kind: s, s: 'artha · ◆ ' + c.id + ' · ' + pathText(c.ni), go: () => { show({t: 'c', k: c.id}, false); revealConcept(k, [s, a]); }}));
  });
  W.forEach(r => {
    const ks = akConcepts.get(r[3]) || [];
    IDX.push({l: r[0], kind: 'word', s: r[3] + (ks.length ? ' · ' + pathText(C[ks[0]].ni) : ''), go: () => show({t: 'w', k: r[4]})});
  });
  DH.forEach(d => IDX.push({l: d.d, alt: d.au, kind: 'dhātu', s: [d.au, d.id, d.raw].filter(Boolean).join(' · '), go: () => show({t: 'd', k: d.id})}));
  UP.forEach(u => IDX.push({l: u.f, kind: 'upasarga', s: [u.u + '+' + (u.bd || ''), u.raw].filter(Boolean).join(' · '), go: () => show({t: 'u', k: u.key})}));
}
const q = document.getElementById('q'), results = document.getElementById('results');
let timer, sel = -1, shown = [];
q.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(search, 120); });
q.addEventListener('focus', () => { if (q.value.trim()) search(); });
q.addEventListener('keydown', e => {
  if (e.key === 'Escape'){ q.value = ''; closeResults(); q.blur(); }
  else if (e.key === 'ArrowDown' || e.key === 'ArrowUp'){
    e.preventDefault(); if (!shown.length) return;
    sel = (sel + (e.key === 'ArrowDown' ? 1 : -1) + shown.length) % shown.length; markSel();
  } else if (e.key === 'Enter' && shown.length){ choose(shown[Math.max(sel, 0)]); }
});
document.addEventListener('click', e => { if (!e.target.closest('.searchbox')) closeResults(); });
function closeResults(){ results.hidden = true; results.replaceChildren(); shown = []; sel = -1; }
function markSel(){ [...results.querySelectorAll('.res')].forEach((r, i) => r.classList.toggle('sel', i === sel)); results.querySelector('.sel')?.scrollIntoView({block: 'nearest'}); }
function choose(e){ closeResults(); q.blur(); e.go(); }
function search(){
  const t = q.value.trim();
  if (!t){ closeResults(); return; }
  if (!IDX) buildIndex();
  const exact = [], pre = [], sub = [];
  for (const e of IDX){
    if (e.l === t || e.alt === t) exact.push(e);
    else if (e.l.startsWith(t) || (e.alt && e.alt.startsWith(t))) pre.push(e);
    else if (e.l.includes(t) || (e.alt && e.alt.includes(t))) sub.push(e);
  }
  const all = exact.concat(pre, sub);
  shown = all.slice(0, 150); sel = -1;
  results.replaceChildren();
  if (!all.length) results.append(h('div', 'res-more', 'No matches'));
  shown.forEach(e => {
    const cls = {ak: 't-ak', word: 't-ak', dp: 't-dp', 'dhātu': 't-dp', upasarga: 't-dp', sc: 't-sc'}[e.kind] || 't-mut';
    const r = h('div', 'res', h('span', 'kind ' + cls, e.kind), h('span', null, e.l), h('small', null, e.s));
    r.onclick = () => choose(e);
    results.append(r);
  });
  if (all.length > shown.length) results.append(h('div', 'res-more', '… ' + (all.length - shown.length) + ' more, refine the search'));
  results.hidden = false;
}

// ---------------------------------------------------------------- resizable split
const mainEl = document.querySelector('main'), split = document.getElementById('split');
function setLeft(pct){ pct = Math.min(75, Math.max(15, pct)); mainEl.style.setProperty('--left', pct + '%'); return pct; }
setLeft(store.get('ct.left', 30));
split.addEventListener('pointerdown', e => {
  e.preventDefault(); split.setPointerCapture(e.pointerId); document.body.classList.add('dragging');
  const move = ev => { const r = mainEl.getBoundingClientRect(); store.set('ct.left', setLeft((ev.clientX - r.left) / r.width * 100)); };
  const up = () => { split.removeEventListener('pointermove', move); split.removeEventListener('pointerup', up); document.body.classList.remove('dragging'); };
  split.addEventListener('pointermove', move); split.addEventListener('pointerup', up);
});
split.addEventListener('dblclick', () => store.set('ct.left', setLeft(30)));

// ---------------------------------------------------------------- buttons, start
document.getElementById('collapse').onclick = () => {
  Object.values(nodeEl).forEach(w => w._open(false));
  treeEl.scrollTop = 0;
};
const withArthas = C.map((c, k) => k).filter(k => C[k].ar.length);
document.getElementById('random').onclick = () => {
  const k = withArthas[Math.floor(Math.random() * withArthas.length)];
  show({t: 'c', k: C[k].id});
};

const start = parseHash();
if (start) render(start, true);
else { cardEl.replaceChildren(helpCard()); drawRecent(); }
})();
