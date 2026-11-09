'use strict';
/* Seed Hunter - interface. JS puro, sem build. Servida pelo proprio BlueMap em /ui/ (mesma origem do mapa). */

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const store = {
  get(k, d) { try { const v = localStorage.getItem('sh.' + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem('sh.' + k, JSON.stringify(v)); } catch { /* modo privado: segue sem salvar */ } },
};

// alvo do /locate -> [nome, tipo, cor, rotulo curto da tag]
const LABELS = {
  'structure #minecraft:village': ['Vila', 'estrutura', '#F2B33D', 'Vila'],
  'structure minecraft:trial_chambers': ['Trial Chamber (subterrânea)', 'estrutura', '#6FB7E8', 'Trial Chamber'],
  'structure #minecraft:ruined_portal': ['Portal em ruínas', 'estrutura', '#B78CF0', 'Portal em ruínas'],
  'structure minecraft:pillager_outpost': ['Posto de saqueadores', 'estrutura', '#E8935A', 'Posto de saqueadores'],
  'structure minecraft:ancient_city': ['Cidade antiga', 'estrutura', '#4DD0C4', 'Cidade antiga'],
  'structure minecraft:mansion': ['Mansão', 'estrutura', '#C08A5A', 'Mansão'],
  'biome minecraft:cherry_grove': ['Cerejeiras', 'bioma', '#E6A8C9', 'Cerejeiras'],
  'biome minecraft:dappled_forest': ['Dappled Forest', 'bioma', '#D9783B', 'Dappled Forest'],
  'biome minecraft:meadow': ['Prado', 'bioma', '#8FBF5A', 'Prado'],
  'biome minecraft:jagged_peaks': ['Picos', 'bioma', '#C9D2DC', 'Picos'],
  'biome minecraft:mushroom_fields': ['Cogumelos', 'bioma', '#B07AA1', 'Cogumelos'],
  'biome minecraft:ice_spikes': ['Espinhos de gelo', 'bioma', '#A8DADC', 'Espinhos de gelo'],
};
const VILLAGE = 'structure #minecraft:village';
function label(key) {
  if (LABELS[key]) return LABELS[key];
  const [kind, id = key] = key.split(' ');
  const nome = id.replace(/^#?minecraft:/, '').replace(/_/g, ' ');
  return [nome, kind === 'biome' ? 'bioma' : 'estrutura', '#9AA6B2', nome];
}
// A distancia de /locate pode vir do CSV antigo sem coordenadas ({dist} apenas)
const found = (s) => Object.entries(s.achados || {}).filter(([, v]) => v);
const villageDist = (s) => { const v = (s.achados || {})[VILLAGE]; return v ? v.dist : null; };
const NEAR = 1000;   // so o que esta perto vira tag/contagem na biblioteca (uma mansao a 8 km nao ajuda ninguem)
const near = (s) => found(s).filter(([, v]) => v.dist <= NEAR);
const tagsOf = (s) => near(s).sort((a, b) => a[1].dist - b[1].dist).map(([k]) => label(k)[3]);
const fmtDist = (d) => (d == null ? '—' : d + ' m');

let DATA = null;
const state = {
  filter: store.get('filter', 'todas'), sort: store.get('sort', 'vila'), q: '',
  favs: store.get('favs', {}), chosen: store.get('chosen', {}), notes: store.get('notes', {}),
};
const save = () => { store.set('filter', state.filter); store.set('sort', state.sort); store.set('favs', state.favs); store.set('chosen', state.chosen); store.set('notes', state.notes); };

/* ------------------------------ miniatura ------------------------------ */
// Os tiles lowres do BlueMap (nivel 1) tem 501x1002: a metade de cima e a imagem vista de cima.
// Cada tile cobre 500 blocos; desenhamos os que tocam a area em volta do centro (o spawn) e recortamos 960x510 blocos.
const centerOf = (s) => s.centro || s.spawn || { x: 0, z: 0 };
// o Chunky gera chunks inteiros, entao a borda da area fica em branco: recorta 450 blocos (nao 480) para cada lado
const viewOf = (s) => { const c = centerOf(s); return { x0: c.x - 450, z0: c.z - 239, w: 900, h: 478 }; };
function drawThumb(canvas, s) {
  const V = viewOf(s), W = (canvas.width = 320), H = (canvas.height = 170), k = W / V.w;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#16202B'; ctx.fillRect(0, 0, W, H);
  for (let tx = Math.floor(V.x0 / 500); tx <= Math.floor((V.x0 + V.w) / 500); tx++)
    for (let tz = Math.floor(V.z0 / 500); tz <= Math.floor((V.z0 + V.h) / 500); tz++) {
      const img = new Image();
      img.onload = () => ctx.drawImage(img, 0, 0, 501, 501, (tx * 500 - V.x0) * k, (tz * 500 - V.z0) * k, 501 * k, 501 * k);
      img.src = `../maps/${s.id}/tiles/1/x${tx}/z${tz}.png`;
    }
}
function pinPos(s) {
  const V = viewOf(s), p = s.spawn || centerOf(s);
  const x = ((p.x - V.x0) / V.w) * 100, z = ((p.z - V.z0) / V.h) * 100;
  return `left:${Math.min(98, Math.max(2, x))}%;top:${Math.min(96, Math.max(4, z))}%`;
}

/* ------------------------------ biblioteca ------------------------------ */
function visibleSeeds() {
  const q = state.q.trim().toLowerCase();
  const ok = (s) => s.status === 'ok';
  let list = DATA.seeds.filter((s) => {
    const f = state.filter;
    if (f === 'favoritas' && !state.favs[s.seed]) return false;
    if (f === 'escolhidas' && !state.chosen[s.seed]) return false;
    if (f === 'aprovadas' && !ok(s)) return false;
    if (f === 'reprovadas' && s.status !== 'reprovada') return false;
    if (!q) return true;
    return s.seed.includes(q) || tagsOf(s).some((t) => t.toLowerCase().includes(q));
  });
  const inf = (d) => (d == null ? Infinity : d);
  const sorts = {
    vila: (a, b) => inf(villageDist(a)) - inf(villageDist(b)),
    recente: (a, b) => (b.quando || '').localeCompare(a.quando || ''),
    achados: (a, b) => near(b).length - near(a).length,
  };
  return list.sort(sorts[state.sort] || sorts.vila);
}

function card(s) {
  const ok = s.status === 'ok';
  const fav = !!state.favs[s.seed];
  const tags = tagsOf(s).slice(0, 4);
  const thumb = s.mapa
    ? `<canvas data-thumb="${esc(s.id)}" aria-hidden="true"></canvas><div class="pin" role="img" aria-label="Spawn" title="Spawn" style="${pinPos(s)}"></div>`
    : `<div class="none">${ok ? 'Mapa não encontrado' : 'Seed descartada no filtro: sem mapa'}</div>`;
  const badge = ok ? '<span class="badge ok">Aprovada</span>'
    : s.status === 'reprovada' ? '<span class="badge bad">Reprovada</span>' : `<span class="badge bad">${esc(s.status)}</span>`;
  const head = `<div class="thumb">${thumb}${badge}</div>
    <div class="head"><h2>Seed ${esc(s.seed.length > 12 ? s.seed.slice(0, 11) + '…' : s.seed)}</h2>${s.seed.length > 12 ? `<p class="sub">${esc(s.seed)}</p>` : ''}</div>`;
  const inner = s.mapa ? `<a class="link" href="#/seed/${esc(s.id)}">${head}</a>` : `<div class="link">${head}</div>`;
  return `<article class="card">${inner}
    <div class="tags">${tags.map((t) => `<span class="tag">${esc(t)}</span>`).join('')}</div>
    <div class="foot"><div class="stats">
      <div class="lead"><span>Vila</span><strong>${fmtDist(villageDist(s))}</strong></div>
      <div title="Estruturas e biomas a até ${NEAR} m do spawn"><span>Por perto</span><strong>${near(s).length}</strong></div></div>
      <button type="button" class="icon-btn" data-fav="${esc(s.seed)}" aria-pressed="${fav}" aria-label="${fav ? 'Tirar dos favoritos' : 'Marcar como favorita'}">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="${fav ? '#F2B33D' : 'none'}" stroke="#F2B33D" stroke-width="1.8" stroke-linejoin="round" aria-hidden="true"><path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2L12 17.3 6.4 20.2l1.1-6.2L3 9.6l6.2-.9Z"/></svg>
      </button></div></article>`;
}

function renderLibrary() {
  const all = DATA.seeds;
  const defs = [
    ['todas', 'Todas', all.length],
    ['favoritas', 'Favoritas', all.filter((s) => state.favs[s.seed]).length],
    ['escolhidas', 'Escolhidas', all.filter((s) => state.chosen[s.seed]).length],
    ['aprovadas', 'Aprovadas', all.filter((s) => s.status === 'ok').length],
    ['reprovadas', 'Reprovadas', all.filter((s) => s.status === 'reprovada').length],
  ];
  const list = visibleSeeds();
  $('#app').innerHTML = `<main class="lib">
  <header>
    <div class="brand"><div class="logo"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#1A1306" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3 20 7.5v9L12 21l-8-4.5v-9Z"/><path d="M12 12 20 7.5M12 12 4 7.5M12 12v9"/></svg></div>
      <div><h1>Seed Hunter</h1><p>${all.length} seeds testadas · ${defs[3][2]} aprovadas · Minecraft 26.3</p></div></div>
    <div class="tools">
      <label class="search"><span class="sr">Buscar seed</span>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#9AA6B2" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
        <input id="q" type="search" placeholder="Buscar seed, bioma ou estrutura" value="${esc(state.q)}"></label>
      <button type="button" class="btn primary" id="more">Gerar mais seeds</button>
    </div>
  </header>
  <div class="bar">
    <div class="chips" role="group" aria-label="Filtrar seeds">${defs.map(([id, nome, n]) => `<button type="button" class="chip" data-filter="${id}" aria-pressed="${state.filter === id}">${nome}<small>${n}</small></button>`).join('')}</div>
    <label class="sort">Ordenar por
      <select id="sort">${[['vila', 'Vila mais perto do spawn'], ['achados', 'Mais achados'], ['recente', 'Mais recente']].map(([v, t]) => `<option value="${v}"${state.sort === v ? ' selected' : ''}>${t}</option>`).join('')}</select></label>
  </div>
  ${list.length ? `<div class="grid">${list.map(card).join('')}</div>`
    : `<div class="empty">${all.length ? 'Nenhuma seed neste filtro.' : 'Ainda não há seeds. Rode <code>python seed_hunter.py</code> para gerar as primeiras.'}</div>`}
  </main>`;
  document.querySelectorAll('canvas[data-thumb]').forEach((c) => drawThumb(c, all.find((s) => s.id === c.dataset.thumb)));
  const q = $('#q');
  q.addEventListener('input', () => { state.q = q.value; const pos = q.selectionStart; renderLibrary(); const n = $('#q'); n.focus(); n.setSelectionRange(pos, pos); });
  $('#sort').addEventListener('change', (e) => { state.sort = e.target.value; save(); renderLibrary(); });
  $('#more').addEventListener('click', () => openDialog('Gerar mais seeds',
    'A geração roda no terminal, com o servidor de Minecraft em segundo plano. Depois recarregue esta página.',
    'python seed_hunter.py --random 50\n# ou liste as seeds em seeds.txt e rode:\npython seed_hunter.py'));
  document.querySelectorAll('[data-filter]').forEach((b) => b.addEventListener('click', () => { state.filter = b.dataset.filter; save(); renderLibrary(); }));
  document.querySelectorAll('[data-fav]').forEach((b) => b.addEventListener('click', () => { const k = b.dataset.fav; state.favs[k] = !state.favs[k]; save(); renderLibrary(); }));
}

/* ------------------------------ inspetor ------------------------------ */
function parseHash(h) {
  const p = (h || '').replace(/^#/, '').split(':');
  return { map: p[0], x: +p[1], y: +p[2], z: +p[3], dist: +p[4], rot: +p[5], angle: +p[6], mode: p[9] || 'perspective' };
}
const mkHash = (m, x, y, z, dist, mode) => `#${m}:${Math.round(x)}:${Math.round(y)}:${Math.round(z)}:${dist}:0:${mode === 'flat' ? 0 : 0.8}:0:0:${mode}`;

let poll = null;
function renderInspector(id) {
  const s = DATA.seeds.find((x) => x.id === id && x.mapa);
  if (!s) { location.hash = '#/'; return; }
  const sp = s.spawn || { x: 0, y: 80, z: 0 };
  const places = found(s).map(([k, v]) => ({ key: k, nome: label(k)[0], tipo: label(k)[1], cor: label(k)[2], ...v }));
  let tab = places.some((p) => p.tipo === 'estrutura') ? 'estrutura' : 'bioma';
  let sel = null, view = { map: s.id, mode: 'perspective' }, noteOpen = false;
  // painel recolhido: libera o mapa e o menu do proprio BlueMap (seletor de mapas, distancia de render...)
  let collapsed = store.get('panel', false);
  const setCollapsed = (v) => {
    collapsed = v; store.set('panel', v);
    $('.insp').classList.toggle('collapsed', v);
    if (v) $('#expand').focus(); else $('#collapse').focus();
  };

  const frameSrc = `../${mkHash(s.id, sp.x, sp.y, sp.z, 300, 'perspective')}`;
  const draw = () => {
    const list = places.filter((p) => p.tipo === tab).sort((a, b) => a.dist - b.dist);
    const n = (t) => places.filter((p) => p.tipo === t).length;
    const chosen = !!state.chosen[s.seed];
    const ctr = centerOf(s);
    const outside = (p) => p.x != null && Math.max(Math.abs(p.x - ctr.x), Math.abs(p.z - ctr.z)) > s.raio;   // alem do que o Chunky gerou
    $('.side').innerHTML = `
    <div class="top">
      <div class="row" style="align-items:center"><a class="back" href="#/"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m15 18-6-6 6-6"/></svg>Biblioteca</a>
        <button type="button" class="btn" id="collapse" aria-expanded="true" style="height:36px;padding:0 12px;font-size:13px">Recolher painel</button></div>
      <div class="row"><div><h1>Seed <span class="mono" style="font-size:16px;font-weight:500">${esc(s.seed)}</span></h1></div>
        <button type="button" class="icon-btn" id="copy" aria-label="Copiar seed"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#C9D2DC" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/></svg></button></div>
      <div class="boxes"><div class="box"><span>Spawn</span><b>${sp.x}, ${sp.y}, ${sp.z}</b></div>
        <div class="box"><span>Área</span><b>${s.raio * 2}×${s.raio * 2}</b></div>
        <div class="box"><span>Geração</span><b>${s.minutos} min</b></div></div>
    </div>
    <div class="tabs" role="group" aria-label="Tipo de local">
      <button type="button" class="tab" data-tab="estrutura" aria-pressed="${tab === 'estrutura'}">Estruturas <small>${n('estrutura')}</small></button>
      <button type="button" class="tab" data-tab="bioma" aria-pressed="${tab === 'bioma'}">Biomas <small>${n('bioma')}</small></button></div>
    <div class="places">${list.length ? list.map((p) => `<button type="button" class="place${outside(p) ? ' out' : ''}" data-place="${esc(p.key)}" aria-pressed="${sel === p.key}">
        <i style="background:${p.cor}"></i><span class="t"><span>${esc(p.nome)}</span><small>${p.x != null ? `X ${p.x} · Y ${p.y ?? '~'} · Z ${p.z}` : 'sem coordenadas (rode de novo)'}</small>${outside(p) ? '<span class="out-tag" title="O mapa só cobre 480 blocos em volta do spawn: ali está vazio">fora da área gerada</span>' : ''}</span><em>${p.dist} m</em></button>`).join('')
      : '<div class="empty" style="padding:24px 12px">Nada deste tipo foi encontrado perto do spawn.</div>'}</div>
    ${noteOpen ? `<div class="note"><label class="sr" for="note">Anotação</label><textarea id="note" placeholder="Anotação sobre esta seed">${esc(state.notes[s.seed] || '')}</textarea></div>` : ''}
    <div class="acts"><button type="button" class="btn" id="noteBtn" aria-expanded="${noteOpen}">${state.notes[s.seed] ? 'Anotação ✎' : 'Anotar'}</button>
      <button type="button" class="btn primary" id="choose" aria-pressed="${chosen}">${chosen ? 'Escolhida ✓' : 'Escolher esta seed'}</button></div>`;
    $('#collapse').onclick = () => setCollapsed(true);
    $('#copy').onclick = () => { try { navigator.clipboard.writeText(s.seed); } catch { /* sem clipboard */ } };
    document.querySelectorAll('[data-tab]').forEach((b) => (b.onclick = () => { tab = b.dataset.tab; draw(); }));
    document.querySelectorAll('[data-place]').forEach((b) => (b.onclick = () => {
      sel = b.dataset.place; const p = places.find((x) => x.key === sel);
      if (p.x != null) goto(mkHash(view.map, p.x, p.y ?? 72, p.z, 150, view.mode));
      draw();
    }));
    $('#noteBtn').onclick = () => { noteOpen = !noteOpen; draw(); if (noteOpen) $('#note').focus(); };
    const note = $('#note'); if (note) note.oninput = () => { state.notes[s.seed] = note.value; save(); };
    $('#choose').onclick = () => { state.chosen[s.seed] = !state.chosen[s.seed]; save(); draw(); };
  };
  const frame = () => $('#bm');
  const goto = (hash) => { try { frame().contentWindow.location.hash = hash; } catch { frame().src = '../' + hash; } };
  const drawViews = () => {
    const defs = [['perspectiva', 'Perspectiva', s.id, 'perspective', true], ['cima', 'Vista de cima', s.id, 'flat', true],
      ['cavernas', 'Cavernas', s.id + '_cav', 'perspective', s.cavernas]];
    $('.views').innerHTML = defs.map(([k, t, m, mode, on]) => {
      const pressed = view.map === m && view.mode === mode;
      return `<button type="button" class="view" data-view="${k}" aria-pressed="${pressed}" ${on ? '' : `disabled title="Gere com: python seed_hunter.py --cavernas ${esc(s.seed)}"`}>${t}</button>`;
    }).join('') + `<a class="btn" href="../${mkHash(s.id, sp.x, sp.y, sp.z, 300, 'perspective')}" target="_blank" rel="noopener">Abrir no BlueMap</a>
      <button type="button" class="btn" id="play">Jogar no Minecraft</button>`;
    $('#play').onclick = () => openDialog('Jogar esta seed no Minecraft',
      'Copia o mundo já gerado para a pasta de mundos do jogo. Depois abra o Minecraft 26.3, vá em Um jogador e procure SeedHunter_' + s.id.replace(/^seed_/, '') + '. Fora da área gerada o jogo continua gerando o mesmo terreno. Se o mundo já estiver lá, ele não é sobrescrito, então seu progresso fica seguro.',
      `python seed_hunter.py --jogar ${s.seed}`);
    document.querySelectorAll('[data-view]').forEach((b) => (b.onclick = () => {
      const d = defs.find((x) => x[0] === b.dataset.view), c = parseHash(frame().contentWindow.location.hash);
      const x = isFinite(c.x) ? c.x : sp.x, y = isFinite(c.y) ? c.y : sp.y, z = isFinite(c.z) ? c.z : sp.z;
      goto(mkHash(d[2], x, y, z, d[3] === 'flat' ? 600 : (isFinite(c.dist) && c.dist ? c.dist : 300), d[3]));
    }));
  };

  $('#app').innerHTML = `<div class="insp${collapsed ? ' collapsed' : ''}"><iframe id="bm" title="Mapa 3D da seed" src="${frameSrc}"></iframe>
    <aside class="side"></aside><button type="button" class="btn expand" id="expand">Mostrar painel</button><div class="views" role="group" aria-label="Modo de visão"></div>
    <div class="cam"><div class="n" aria-hidden="true">N</div><div><small>Câmera</small><span id="camtxt">—</span></div></div></div>`;
  draw(); drawViews();
  $('#expand').onclick = () => setCollapsed(false);
  clearInterval(poll);
  poll = setInterval(() => {   // le a camera do iframe (mesma origem): leitura e botoes de visao
    try {
      const c = parseHash(frame().contentWindow.location.hash);
      if (!isFinite(c.x)) return;
      $('#camtxt').textContent = `X ${Math.round(c.x)} · Y ${Math.round(c.y)} · Z ${Math.round(c.z)}`;
      if (c.map !== view.map || c.mode !== view.mode) { view = { map: c.map, mode: c.mode }; drawViews(); }
    } catch { clearInterval(poll); }
  }, 500);
}

/* ------------------------------ dialogo e rotas ------------------------------ */
function openDialog(titulo, texto, codigo) {
  const d = $('#dlg');
  d.innerHTML = `<h2 id="dlg-title">${esc(titulo)}</h2><p>${esc(texto)}</p><code class="code">${esc(codigo)}</code>
    <div class="acts"><button type="button" class="btn" id="dcopy">Copiar comando</button><button type="button" class="btn primary" id="dclose">Fechar</button></div>`;
  $('#dclose').onclick = () => d.close();
  $('#dcopy').onclick = () => { try { navigator.clipboard.writeText(codigo.split('\n')[0]); } catch { /* sem clipboard */ } };
  d.showModal();
}

function route() {
  clearInterval(poll);
  const m = location.hash.match(/^#\/seed\/(.+)$/);
  if (m) renderInspector(decodeURIComponent(m[1])); else renderLibrary();
}

fetch('index.json', { cache: 'no-store' }).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
  .then((d) => { DATA = d; window.addEventListener('hashchange', route); route(); })
  .catch(() => { $('#app').innerHTML = '<div class="lib"><div class="empty">Não achei o <code>index.json</code>.<br>Rode <code>python seed_hunter.py --reindex</code> e abra <code>http://localhost:8100/ui/</code>.</div></div>'; });
