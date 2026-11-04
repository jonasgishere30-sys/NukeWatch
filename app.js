/* NukeWatch front end (minimal style). Reads data/latest.json and refreshes every minute.
   Text from outside sources is always inserted with textContent, never innerHTML. */
(function () {
  'use strict';

  var LEVELS = ['Baseline', 'Watch', 'Elevated', 'High', 'Severe'];
  var LCOL = ['#7FD1A5', '#FFB547', '#FF9F5A', '#FF7A59', '#FF4D3D'];
  var RULES = [
    ['0–19', 'No flashpoint above rung 2. Strategic forces look normal.'],
    ['20–39', 'A nuclear-armed state is fighting or making direct threats. Nuclear forces look normal.'],
    ['40–59', 'Nuclear drills, doctrine changes or explicit threats, plus other signals above normal.'],
    ['60–79', 'Strategic forces changing in several unrelated ways outside exercises.'],
    ['80–100', 'Subs sailing, bombers dispersed, embassies evacuating, airspace closing, all at once.']
  ];
  var RUNGS = ['Rhetoric & sanctions', 'Buildup & tests', 'Conventional fighting', 'Nuclear signaling', 'Strategic forces moving', 'Nuclear use'];
  var RUNGD = ['Threats, sanctions, expelled diplomats.', 'Troops massing, exercises, missile tests.', 'Open war involving a nuclear-armed state or ally.',
    'Nuclear drills, doctrine changes, explicit threats.', 'Bombers dispersed, subs surged, forces on alert.', 'Any nuclear detonation in conflict.'];
  var RC = ['#A3A39C', '#F5F5F0', '#FFB547', '#FF7A59', '#FF4D3D', '#FF2E2E'];
  var CAT = { command: ['Airborne command', '#FF7A59'], bomber: ['Bomber', '#FF9F5A'], tanker: ['Tanker', '#FFB547'], recon: ['Recon', '#A3A39C'], airlift: ['Airlift', '#8EB8E5'] };
  var SITES = [
    ['Washington, D.C.', 38.9, -77.0], ['Offutt AFB (STRATCOM), Nebraska', 41.12, -95.91], ['Minot AFB, North Dakota', 48.42, -101.36],
    ['Malmstrom AFB, Montana', 47.5, -111.18], ['F.E. Warren AFB, Wyoming', 41.13, -104.87], ['Kings Bay sub base, Georgia', 30.8, -81.52],
    ['Kitsap-Bangor sub base, Washington', 47.73, -122.71], ['Whiteman AFB, Missouri', 38.73, -93.55], ['Barksdale AFB, Louisiana', 32.5, -93.66],
    ['Moscow', 55.75, 37.62], ['Kozelsk ICBM division, Russia', 54.03, 35.78], ['Gadzhiyevo sub base, Kola', 69.25, 33.33],
    ['Engels Air Base, Russia', 51.48, 46.2], ['Beijing', 39.9, 116.4], ['Yulin Naval Base, Hainan', 18.22, 109.55],
    ['Faslane, Scotland', 56.07, -4.82], ['Île Longue, France', 48.3, -4.52]
  ];

  var state = { data: null, fp: null, yieldKt: 300, site: 0, layers: { conflict: true, aircraft: true, seismic: true, sites: false } };
  var countryNames = {}, countriesGeo = null;

  // ---------- helpers ----------
  function $(id) { return document.getElementById(id); }
  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    if (attrs) for (var k in attrs) {
      var v = attrs[k];
      if (v === null || v === undefined) continue;
      if (k === 'text') n.textContent = v;
      else if (k === 'style') n.style.cssText = v;
      else if (k.slice(0, 2) === 'on') n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v);
    }
    (kids || []).forEach(function (c) { if (c !== null && c !== undefined) n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  }
  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); return n; }
  function safeUrl(u) { return /^https?:\/\//i.test(u || '') ? u : null; }
  function ago(iso) {
    if (!iso) return '';
    var s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 90) return 'just now';
    if (s < 3600) return Math.round(s / 60) + 'm ago';
    if (s < 86400) return Math.round(s / 3600) + 'h ago';
    return Math.round(s / 86400) + 'd ago';
  }
  function hhmm(iso) { var d = new Date(iso); return isNaN(d) ? '' : d.toISOString().slice(11, 16); }
  function fpById(id) { return ((state.data || {}).flashpoints || []).filter(function (f) { return f.id === id; })[0]; }
  function roles(f) { var c = f.countries || {}; return Array.isArray(c) ? { party: c.slice(0, 2), involved: c.slice(2), threatened: [] } : c; }
  function names(ids) { return (ids || []).map(function (i) { return countryNames[i] || i; }).join(', ') || '—'; }
  function src(name) { return (((state.data || {}).sources) || {})[name] || null; }
  function srcState(prefix) {
    // worst state among sources whose name is prefix or starts with "prefix:"
    var order = { failed: 5, not_configured: 4, skipped: 3, stale: 2, cached: 1, ok: 0 }, worst = null;
    var all = ((state.data || {}).sources) || {};
    Object.keys(all).forEach(function (k) { if (k === prefix || k.indexOf(prefix + ':') === 0) { var st = all[k]; if (!worst || order[st.state] > order[worst.state]) worst = st; } });
    return worst;
  }
  function mins(m) { return m == null ? '' : m < 60 ? m + ' min' : m < 1440 ? Math.round(m / 60) + ' h' : Math.round(m / 1440) + ' d'; }
  function stateNote(prefix) {
    var st = srcState(prefix);
    if (!st) return null;
    if (st.state === 'stale') return el('p', { class: 'note warn-note', text: 'Showing data from ' + mins(st.age_min) + ' ago. The latest fetch failed: ' + (st.error || '') });
    if (st.state === 'failed') return el('p', { class: 'note warn-note', text: 'Unavailable this scan: ' + (st.error || 'unknown error') });
    if (st.state === 'skipped') return el('p', { class: 'note', text: 'Not refreshed this scan (request budget). ' + (st.last_ok ? 'Last good data ' + ago(st.last_ok) + '.' : '') });
    if (st.state === 'not_configured') return el('p', { class: 'note', text: 'Not set up: ' + (st.note || '') });
    return null;
  }
  function unavailable(box, prefix, fallbackText) {
    var n = stateNote(prefix);
    box.appendChild(n || el('p', { class: 'note', text: fallbackText }));
  }
  function row(label, value, color) { return el('div', { class: 'row' }, [el('span', { text: label }), el('span', { class: 'v', style: color ? 'color:' + color : '', text: value })]); }

  // ---------- map ----------
  var map = L.map('map', { worldCopyJump: true, minZoom: 1.5, zoomSnap: 0.5, scrollWheelZoom: false }).setView([35, 30], 1.5);
  map.on('focus click', function () { map.scrollWheelZoom.enable(); });
  // Free basemap, no API key (Esri World Dark Gray Canvas). If it ever fails, the country outlines below still show.
  var ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/';
  L.tileLayer(ESRI + 'World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
    attribution: 'Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors', maxZoom: 16
  }).addTo(map);
  L.tileLayer(ESRI + 'World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}', { maxZoom: 16, pane: 'shadowPane' }).addTo(map);
  var baseLayer = L.layerGroup().addTo(map);
  var groups = { conflict: L.layerGroup().addTo(map), aircraft: L.layerGroup().addTo(map), seismic: L.layerGroup().addTo(map), sites: L.layerGroup() };
  var ringLayer = L.layerGroup().addTo(map);

  fetch('countries.geojson').then(function (r) { return r.json(); }).then(function (g) {
    countriesGeo = g;
    g.features.forEach(function (f) { if (f.id != null) countryNames[String(f.id)] = f.properties.name; });
    // Neutral outline of every country, drawn under the highlights.
    L.geoJSON(g, { interactive: false, style: { color: '#3A3A36', weight: 0.6, fillColor: '#1A1A18', fillOpacity: 0.55 } }).addTo(baseLayer);
    if (state.data) { drawConflict(); renderTies(state.data); }
  });

  function drawToggles() {
    var box = clear($('layers'));
    [['conflict', 'Conflicts', '#FF4D3D'], ['aircraft', 'Aircraft', '#FFB547'], ['seismic', 'Test-site quakes', '#B48EF0'], ['sites', 'Strategic sites', '#A3A39C']].forEach(function (b) {
      box.appendChild(el('button', { type: 'button', 'aria-pressed': String(state.layers[b[0]]), onclick: function () {
        state.layers[b[0]] = !state.layers[b[0]];
        if (state.layers[b[0]]) groups[b[0]].addTo(map); else map.removeLayer(groups[b[0]]);
        drawToggles();
      } }, [el('i', { style: 'background:' + b[2] }), b[1]]));
    });
  }

  function drawConflict() {
    var g = groups.conflict; g.clearLayers();
    // Colour by ROLE (side / involved / threatened); brightness by how high the flashpoint's rung is.
    // A country in several conflicts takes its strongest role (side > involved > threatened).
    var RANK = { party: 3, involved: 2, threatened: 1 };
    var best = {}, ties = {};
    state.data.flashpoints.forEach(function (f) {
      if (f.rung === null || f.rung === undefined) return;  // no data: don't paint guesses on the map
      var c = roles(f);
      ['party', 'involved', 'threatened'].forEach(function (role) {
        (c[role] || []).forEach(function (id) {
          var cur = best[id];
          if (!cur || RANK[role] > RANK[cur.role] || (RANK[role] === RANK[cur.role] && f.rung > cur.rung)) best[id] = { role: role, rung: f.rung };
          var label = role === 'party' ? 'side' : role;
          (ties[id] = ties[id] || []).push(f.name + ' · ' + label + ' · rung ' + f.rung);
        });
      });
    });
    var ROLE_COL = { party: '#FF4D3D', involved: '#FF9F5A', threatened: '#C9B458' };
    if (countriesGeo) {
      L.geoJSON(countriesGeo, {
        filter: function (ft) { return !!best[String(ft.id)]; },
        style: function (ft) {
          var b = best[String(ft.id)], col = ROLE_COL[b.role];
          var op = b.role === 'party' ? 0.18 + 0.07 * b.rung : b.role === 'involved' ? 0.2 : 0.14;
          return { color: col, weight: 1, fillColor: col, fillOpacity: Math.min(op, 0.6) };
        },
        onEachFeature: function (ft, layer) {
          var box = el('div', null, [el('strong', { text: ft.properties.name })]);
          (ties[String(ft.id)] || []).forEach(function (t) { box.appendChild(el('br')); box.appendChild(document.createTextNode(t)); });
          layer.bindTooltip(box, { sticky: true });
        }
      }).addTo(g);
    }
    state.data.flashpoints.forEach(function (f) {
      var nd = f.rung === null || f.rung === undefined, c = nd ? '#8A8A83' : RC[f.rung - 1];
      var m = L.marker([f.lat, f.lon], { title: f.name + (nd ? ' (no data)' : ''), icon: L.divIcon({ className: '', iconSize: null, iconAnchor: [10, 11],
        html: '<span class="fp-marker" style="border-color:' + c + '"><b style="background:' + c + '">' + (nd ? '?' : f.rung) + '</b></span>' }) });
      m.on('add', function () { m.getElement().querySelector('.fp-marker').appendChild(document.createTextNode(f.short)); });
      m.on('click', function () { selectFp(f.id); });
      m.addTo(g);
    });
  }

  function drawAircraft() {
    var g = groups.aircraft; g.clearLayers();
    (state.data.aircraft.tracks || []).forEach(function (a) {
      var c = (CAT[a.category] || ['', '#FFB547'])[1];
      var m = L.marker([a.lat, a.lon], { icon: L.divIcon({ className: '', iconSize: [16, 16], iconAnchor: [8, 8],
        html: '<div style="transform:rotate(' + ((a.track || 0) - 90) + 'deg);color:' + c + '"><svg width="16" height="16" viewBox="-8 -8 16 16"><path d="M7 0 L-5 -4.5 L-2.5 0 L-5 4.5 Z" fill="currentColor"/></svg></div>' }) });
      m.bindTooltip(el('div', null, [el('strong', { text: a.callsign || a.hex }), el('br'),
        document.createTextNode(a.type + ' · ' + (a.ground ? 'on ground' : a.alt ? a.alt.toLocaleString() + ' ft' : '—'))]));
      m.addTo(g);
    });
  }

  function drawSites() {
    SITES.forEach(function (s, i) {
      var m = L.marker([s[1], s[2]], { title: s[0], icon: L.divIcon({ className: '', iconSize: [8, 8], html: '<span class="site-dot" style="background:#A3A39C"></span>' }) });
      m.on('click', function () { state.site = i; $('site-sel').value = String(i); renderRings(); showRings(); });
      m.addTo(groups.sites);
    });
  }

  // ---------- effects ----------
  function radii(Y) {
    var k = Math.pow(Y / 300, 1 / 3);
    return [
      ['Light blast', 'Windows shatter, flying glass (1 psi)', 12.5 * k, '#8EB8E5'],
      ['Thermal', 'Third-degree burns to exposed skin', 9.0 * Math.pow(Y / 300, 0.41), '#FFB547'],
      ['Moderate blast', 'Most homes collapse (5 psi)', 4.7 * k, '#FF9F5A'],
      ['Heavy blast', 'Concrete buildings destroyed (20 psi)', 1.9 * k, '#FF4D3D'],
      ['Fireball', 'Vaporized', 0.69 * Math.pow(Y / 300, 0.4), '#FFE08A']
    ];
  }
  function renderRings() {
    var box = clear($('rings'));
    radii(state.yieldKt).slice().reverse().forEach(function (r) {
      box.appendChild(el('div', { class: 'row' }, [
        el('span', null, [el('span', { style: 'display:inline-block;width:10px;height:10px;border-radius:50%;border:1px solid ' + r[3] + ';margin-right:10px' }), r[0],
          el('span', { class: 'dim small', text: ' · ' + r[1] })]),
        el('span', { class: 'v', style: 'color:' + r[3], text: r[2].toFixed(1) + ' km' })]));
    });
    var yb = clear($('yields'));
    [100, 300, 800].forEach(function (v) {
      yb.appendChild(el('button', { type: 'button', 'aria-pressed': String(v === state.yieldKt), text: v + ' kt', onclick: function () {
        state.yieldKt = v; renderRings(); if (ringLayer.getLayers().length) showRings(true);
      } }));
    });
  }
  function showRings(stay) {
    ringLayer.clearLayers();
    var s = SITES[state.site];
    radii(state.yieldKt).forEach(function (r, i) {
      L.circle([s[1], s[2]], { radius: r[2] * 1000, color: r[3], weight: 1, fillColor: r[3], fillOpacity: i === 4 ? 0.6 : 0.07, interactive: false }).addTo(ringLayer);
    });
    if (!stay) { map.flyTo([s[1], s[2]], 10, { duration: 1.2 }); $('map').scrollIntoView({ behavior: 'smooth', block: 'center' }); }
  }

  // ---------- sections ----------
  function renderTop(d) {
    var c = d.level ? LCOL[d.level - 1] : '#A3A39C';
    var next = new Date(new Date(d.updated).getTime() + 15 * 60000);
    var mins = Math.max(0, Math.round((next - Date.now()) / 60000));
    $('updated').textContent = 'Updated ' + hhmm(d.updated) + ' UTC · ' + (mins > 0 ? 'next in ' + mins + ' min' : 'next scan due');
    $('foot-scan').textContent = 'Last scan ' + d.updated.slice(0, 16).replace('T', ' ') + ' UTC · ' + d.history_days + ' days of history';
    var none = d.score === null || d.score === undefined;
    $('score').textContent = none ? '?' : d.score;
    $('level').textContent = none ? 'INSUFFICIENT DATA · ' + d.coverage.flashpoints_rated + ' OF ' + d.coverage.flashpoints_total + ' FLASHPOINTS HAVE NEWS DATA' : 'LEVEL ' + d.level + ' · ' + LEVELS[d.level - 1].toUpperCase();
    $('level').style.color = none ? '#A3A39C' : c;
    $('headline').textContent = d.summary.headline;
    $('track-fill').style.cssText = none ? 'width:0' : 'width:' + d.score + '%;background:' + c;
    $('track-dot').style.cssText = none ? 'display:none' : 'left:' + d.score + '%;background:' + c;
    $('summary-text').textContent = d.summary.text;
    var ul = clear($('changed'));
    d.summary.changed.forEach(function (x) { ul.appendChild(el('li', { text: x })); });
    var cv = d.coverage || {}, bar = $('error-bar');
    if ((cv.failed || 0) + (cv.stale || 0) > 0) {
      bar.hidden = false; clear(bar);
      bar.appendChild(document.createTextNode((cv.failed || 0) + ' sources failed and ' + (cv.stale || 0) + ' are showing older data on the last scan. '));
      bar.appendChild(el('a', { href: '#diagnostics', text: 'See what went wrong', onclick: function () { $('diagnostics').open = true; } }));
    } else bar.hidden = true;
    document.title = 'NukeWatch · ' + (none ? 'insufficient data' : d.score + ' ' + LEVELS[d.level - 1]);
  }

  function renderTicker(d) {
    var t = clear($('ticker'));
    var items = (d.news || []).slice(0, 20);
    items.concat(items).forEach(function (n) {
      var f = fpById(n.flashpoint) || {};
      t.appendChild(el('a', { href: safeUrl(n.url) || '#', target: '_blank', rel: 'noopener noreferrer' }, [
        el('span', { class: 't', text: hhmm(n.time) + ' · ' + (f.short || '') }), n.title]));
    });
  }

  function renderFlashpoints(d) {
    var box = clear($('fp-list'));
    d.flashpoints.slice().sort(function (a, b) { return (b.rung || 0) - (a.rung || 0) || (b.stories_24h || 0) - (a.stories_24h || 0); }).forEach(function (f) {
      var noData = f.rung === null || f.rung === undefined;
      var why = ((src('news:' + f.id) || {}).error || 'source unavailable');
      var sub = noData ? 'No news data this scan · ' + (why.length > 70 ? why.slice(0, 70) + '…' : why)
        : f.rung_name + (f.stories_24h != null ? ' · ' + f.stories_24h + ' stories/24h' : '') + (f.data_state === 'stale' ? ' · data ' + mins(f.data_age_min) + ' old' : '');
      box.appendChild(el('button', { class: 'fp', type: 'button', 'aria-pressed': String(state.fp === f.id), onclick: function () { selectFp(f.id); } }, [
        el('span', null, [el('span', { class: 'fp-name', text: f.name }), el('span', { class: 'fp-sub', text: sub })]),
        el('span', { class: 'fp-r', style: 'color:' + (noData ? '#8A8A83' : RC[f.rung - 1]), text: noData ? 'No data' : 'R' + f.rung + ' ' + (f.trend || '') })]));
    });
  }

  function renderSignals(d) {
    var box = clear($('signal-list'));
    var acd = d.aircraft || {}, a = acd.counts, g = d.gov || {}, s = d.social || {};
    var acNote = a == null ? 'unavailable' : null, acStale = acd.live === false && a != null ? ' (old)' : '';
    a = a || {};
    var A = '#FFB547';
    function ratio(x) { return x ? x + '×' : '—'; }
    box.appendChild(row('Command aircraft airborne', acNote || String(a.command || 0) + acStale, acNote ? '#8A8A83' : null));
    box.appendChild(row('Bombers airborne', acNote || String(a.bomber || 0) + acStale, acNote ? '#8A8A83' : null));
    box.appendChild(row('Tankers airborne', acNote || String(a.tanker || 0) + acStale, acNote ? '#8A8A83' : null));
    box.appendChild(row('Airlift (C-17 / C-5 / Il-76)', acNote || String(a.airlift || 0) + acStale, acNote ? '#8A8A83' : null));
    var U = '#8A8A83';
    if (d.seismic == null) box.appendChild(row('Shallow quakes at test sites (7d)', 'unavailable', U));
    else { var shallow = d.seismic.filter(function (q) { return q.shallow; }); box.appendChild(row('Shallow quakes at test sites (7d)', String(shallow.length), shallow.length ? '#FF4D3D' : null)); }
    if (d.nav_warnings == null) box.appendChild(row('Missile / rocket sea warnings', 'unavailable', U));
    else { var mw = d.nav_warnings.filter(function (w) { return w.type === 'Missile / rocket'; }).length; box.appendChild(row('Missile / rocket sea warnings', String(mw), mw ? A : null)); }
    if (d.outages == null) box.appendChild(row('Major internet outages', 'unavailable', U));
    else { var bigOut = d.outages.filter(function (o) { return o.score >= 1000; }); box.appendChild(row('Major internet outages', bigOut.length ? bigOut.map(function (o) { return o.name; }).slice(0, 2).join(', ') : '0', bigOut.length ? A : null)); }
    var att = (d.attention || [])[0];
    if (att) box.appendChild(row('Top Wikipedia spike', att.article + ' ' + ratio(att.ratio), att.ratio >= 2 ? A : null));
    var vx = (d.markets || []).filter(function (m) { return m.name.indexOf('VIX') === 0; })[0];
    if (vx) box.appendChild(row('VIX fear index', vx.last.toFixed(1) + ' (' + (vx.change_pct >= 0 ? '+' : '') + vx.change_pct + '%)', vx.change_pct >= 15 ? A : null));
    box.appendChild(row('Nuclear-related news', ratio(d.nuclear_news_ratio), d.nuclear_news_ratio > 1.3 ? A : null));
    box.appendChild(row('Preparedness news', ratio(g.prep_ratio), g.prep_ratio > 1.3 ? A : null));
    if (g.available === false) { box.appendChild(row('New Level-4 advisories (7d)', 'unavailable', U)); box.appendChild(row('Embassy ordered departures', 'unavailable', U)); }
    else {
      box.appendChild(row('New Level-4 advisories (7d)', String((g.recent_level4 || []).length), (g.recent_level4 || []).length ? A : null));
      box.appendChild(row('Embassy ordered departures', String((g.ordered_departures || []).length), (g.ordered_departures || []).length ? A : null));
    }
    box.appendChild(row('Bluesky chatter', s.bluesky_per_hour != null ? s.bluesky_per_hour + '/hr' + (s.bluesky_ratio ? ' · ' + s.bluesky_ratio + '×' : '') : (srcState('bluesky') || {}).state === 'not_configured' ? 'not set up' : 'unavailable', s.bluesky_ratio > 1.3 ? A : null));
  }

  function newsItem(n, label) {
    var url = safeUrl(n.url), img = safeUrl(n.image);
    var thumb = el(url ? 'a' : 'span', { class: 'thumb', href: url, target: url ? '_blank' : null, rel: url ? 'noopener noreferrer' : null, tabindex: '-1', 'aria-hidden': 'true' });
    if (img) {
      var im = el('img', { src: img, alt: '', loading: 'lazy', referrerpolicy: 'no-referrer' });
      im.addEventListener('error', function () { clear(thumb).appendChild(el('span', { text: n.source || '' })); });
      thumb.appendChild(im);
    } else thumb.appendChild(el('span', { text: n.source || '' }));
    return el('article', { class: 'news' }, [thumb, el('div', null, [
      el('div', { class: 'n-meta', text: [label, n.source, ago(n.time)].filter(Boolean).join(' · ') }),
      url ? el('a', { class: 'n-title', href: url, target: '_blank', rel: 'noopener noreferrer', text: n.title }) : el('span', { class: 'n-title', text: n.title })])]);
  }

  function renderNews(d) {
    var box = clear($('news-list'));
    var list = (d.news || []).filter(function (n) { return !state.fp || n.flashpoint === state.fp; }).slice(0, 7);
    if (!list.length) {
      var dead = (d.flashpoints || []).filter(function (f) { return (!state.fp || f.id === state.fp) && (f.rung === null || f.rung === undefined); });
      box.appendChild(el('p', { class: dead.length ? 'note warn-note' : 'note', text: dead.length ? 'News is unavailable for this scan (see Data sources below). This does not mean nothing is happening.' : 'No stories in the last 24 hours.' }));
    }
    list.forEach(function (n) { var f = fpById(n.flashpoint) || {}; box.appendChild(newsItem(n, f.short)); });
    var f = state.fp && fpById(state.fp);
    $('news-scope').textContent = f ? f.short : 'all';
    $('news-all').hidden = !f;
  }

  function selectFp(id) {
    state.fp = state.fp === id ? null : id;
    var f = state.fp && fpById(state.fp);
    if (f) map.flyTo([f.lat, f.lon], f.zoom, { duration: 1 }); else map.flyTo([35, 30], 1.5);
    renderFlashpoints(state.data); renderNews(state.data);
  }
  $('news-all').addEventListener('click', function () { selectFp(state.fp); });

  function renderIndex(d) {
    $('pts-label').textContent = d.score === null || d.score === undefined ? (d.raw_score + ' (partial)') : d.score;
    var bd = clear($('breakdown'));
    d.breakdown.forEach(function (b) {
      var pct = Math.min(100, b.pts / b.max * 100), col = pct >= 45 ? '#FFB547' : '#F5F5F0';
      bd.appendChild(el('div', { class: 'bd' }, [
        el('div', { class: 'bd-top' }, [el('span', { text: b.name }), el('span', { style: 'color:' + col }, [String(b.pts), el('span', { class: 'dim', text: ' / ' + b.max })])]),
        el('div', { class: 'bar' }, [el('div', { style: 'width:' + pct + '%;background:' + col })]),
        el('div', { class: 'why', text: b.why + (b.coverage === 'partial' ? ' · partial data' : b.coverage === 'none' ? ' · no data' : '') })]));
    });
    $('baseline-note').textContent = d.insufficient ? 'No index this scan: too few flashpoints have news data. Missing data is not counted as calm.' : d.history_days < 3
      ? 'Confidence ' + d.confidence.toLowerCase() + ': still learning what normal looks like (' + d.history_days + ' of 3+ days). Aircraft and social baselines are not counted yet.'
      : 'Confidence ' + d.confidence.toLowerCase() + ' · ' + d.history_days + ' days of history.';
    var lv = clear($('levels'));
    LEVELS.forEach(function (n, i) {
      lv.appendChild(el('div', { class: 'lv' + (d.level && i + 1 === d.level ? ' on' : '') }, [
        el('div', null, [el('div', { style: 'color:' + LCOL[i], text: n }), el('div', { class: 'lv-r', text: RULES[i][0] })]),
        el('p', { text: RULES[i][1] })]));
    });
    var lad = clear($('ladder'));
    RUNGS.forEach(function (n, i) {
      var here = d.flashpoints.filter(function (f) { return f.rung === i + 1; }).map(function (f) { return f.short; }).join(' · ');
      lad.appendChild(el('div', { class: 'rung' }, [el('div', { class: 'n', text: 'Rung ' + (i + 1) }), el('div', { class: 'nm', style: 'color:' + RC[i], text: n }),
        el('div', { class: 'd', text: RUNGD[i] }), el('div', { class: 'here', text: here || '—' })]));
    });
  }

  function renderTies(d) {
    var box = clear($('ties'));
    d.flashpoints.forEach(function (f) {
      var c = roles(f);
      box.appendChild(el('div', { class: 'tie' }, [el('div', { class: 'nm', text: f.name }),
        el('div', null, [el('span', { style: 'color:#FF7A59', text: 'Sides ' }), names(c.party)]),
        el('div', null, [el('span', { style: 'color:#FFB547', text: 'Involved ' }), names(c.involved)]),
        el('div', null, [el('span', { class: 'dim', text: 'Threatened ' }), names(c.threatened)])]));
    });
  }

  function renderGov(d) {
    var g = d.gov || {};
    var box = clear($('gov-news'));
    var prep = g.prep_news || [];
    if (!prep.length) unavailable(box, 'news:gov', 'No preparedness stories in the last 3 days.');
    prep.slice(0, 8).forEach(function (n) { box.appendChild(newsItem(n, n.type)); });
    var counts = {};
    prep.forEach(function (n) { counts[n.type] = (counts[n.type] || 0) + 1; });
    var w = clear($('watch'));
    ['Stock-up advice', 'Shelters', 'Iodine', 'Mobilization', 'Civil defense'].forEach(function (t) {
      var c = counts[t] || 0;
      w.appendChild(row(t, c ? c + ' stories' : 'none', c ? '#FFB547' : '#A3A39C'));
    });
    var l4 = clear($('level4'));
    (g.level4 || []).slice().sort(function (a, b) { return a.country.localeCompare(b.country); }).forEach(function (a) {
      var u = safeUrl(a.url);
      l4.appendChild(u ? el('a', { href: u, target: '_blank', rel: 'noopener noreferrer', text: a.country }) : el('span', { text: a.country }));
    });
    if (g.available === false) l4.appendChild(el('span', { text: 'U.S. advisories unavailable this scan' }));
    else if (!(g.level4 || []).length) l4.appendChild(el('span', { text: 'None' }));
    var od = clear($('ordered'));
    if (!(g.ordered_departures || []).length) od.appendChild(row('None listed', ''));
    (g.ordered_departures || []).forEach(function (a) { od.appendChild(row(a.country, a.time ? a.time.slice(0, 10) : '')); });
  }

  function renderAircraft(d) {
    var a = d.aircraft || {}, c = a.counts || {};
    if (a.counts == null) {
      $('ac-meta').textContent = 'flight feeds unavailable';
      var tb0 = clear($('ac-rows'));
      tb0.appendChild(el('tr', null, [el('td', { colspan: '6', class: 'dim', text: 'Military flight data is unavailable this scan: ' + ((src('aircraft') || {}).error || '') })]));
      return;
    }
    $('ac-meta').textContent = (a.feed || 'feed down') + ' · command ' + (c.command || 0) + ' · bomber ' + (c.bomber || 0) + ' · tanker ' + (c.tanker || 0) + ' · airlift ' + (c.airlift || 0) + ' · recon ' + (c.recon || 0);
    var tb = clear($('ac-rows'));
    var order = ['command', 'bomber', 'tanker', 'airlift', 'recon'];
    var rows = (a.tracks || []).slice().sort(function (x, y) { return order.indexOf(x.category) - order.indexOf(y.category); });
    if (!rows.length) tb.appendChild(el('tr', null, [el('td', { colspan: '6', class: 'dim', text: 'No tracked aircraft of interest are broadcasting right now.' })]));
    rows.forEach(function (r) {
      tb.appendChild(el('tr', { class: 'click', onclick: function () { map.flyTo([r.lat, r.lon], 6); $('map').scrollIntoView({ behavior: 'smooth', block: 'center' }); } }, [
        el('td', { style: 'color:' + (CAT[r.category] || ['', '#F5F5F0'])[1], text: r.callsign || r.hex }), el('td', { text: r.type }),
        el('td', { class: 'dim', text: (CAT[r.category] || [''])[0] }),
        el('td', { class: 'dim', text: r.ground ? 'on ground' : r.alt ? r.alt.toLocaleString() + ' ft' : '—' }),
        el('td', { class: 'dim', text: r.speed ? r.speed + ' kt' : '—' }),
        el('td', { class: 'dim', text: Math.abs(r.lat).toFixed(2) + (r.lat >= 0 ? 'N ' : 'S ') + Math.abs(r.lon).toFixed(2) + (r.lon >= 0 ? 'E' : 'W') })]));
    });
  }

  function renderSocial(d) {
    var s = d.social || {};
    $('soc-meta').textContent = 'Bluesky ' + (s.bluesky_per_hour != null ? s.bluesky_per_hour + ' posts/hr' : 'off') + ' · Mastodon ' + (((d.social_extra || {}).mastodon_per_hour) != null ? d.social_extra.mastodon_per_hour + '/hr' : 'off') + ' · Reddit ' + (s.reddit_hits || 0) + ' matches' + ((d.social_extra || {}).telegram_hits ? ' · Telegram ' + d.social_extra.telegram_hits + ' matches' : '') + ' · nothing counts until confirmed';
    var box = clear($('posts'));
    if (!(s.posts || []).length) box.appendChild(el('p', { class: 'note', text: 'No posts collected on the last scan.' }));
    (s.posts || []).slice(0, 8).forEach(function (p) {
      var u = safeUrl(p.url);
      box.appendChild(el('div', { class: 'post' }, [
        el('div', { class: 'm' }, [el('span', { text: [p.platform, p.author, ago(p.time)].filter(Boolean).join(' · ') }), el('span', { style: 'color:#FFB547', text: 'Unverified' })]),
        el('div', { class: 't', text: p.text }),
        u ? el('a', { class: 'small dim', href: u, target: '_blank', rel: 'noopener noreferrer', text: 'Open post' }) : null]));
    });
  }

  function spark(vals, color) {
    var ns = 'http://www.w3.org/2000/svg', w = 80, h = 20;
    var svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('viewBox', '0 0 ' + w + ' ' + h); svg.setAttribute('width', w); svg.setAttribute('height', h); svg.setAttribute('aria-hidden', 'true');
    if (vals && vals.length > 1) {
      var mx = Math.max.apply(null, vals), mn = Math.min.apply(null, vals), rg = (mx - mn) || 1;
      var pl = document.createElementNS(ns, 'polyline');
      pl.setAttribute('points', vals.map(function (v, i) { return (i / (vals.length - 1) * w).toFixed(1) + ',' + (h - 2 - (v - mn) / rg * (h - 4)).toFixed(1); }).join(' '));
      pl.setAttribute('fill', 'none'); pl.setAttribute('stroke', color || '#A3A39C'); pl.setAttribute('stroke-width', '1.4');
      svg.appendChild(pl);
    }
    return svg;
  }
  function ratioBar(label, r, sub) {
    var hot = r != null && r >= 1.8, warm = r != null && r >= 1.3;
    var col = hot ? '#FF7A59' : warm ? '#FFB547' : '#F5F5F0';
    var pct = r == null ? 0 : Math.min(100, r / 3 * 100);
    return el('div', { class: 'bd' }, [
      el('div', { class: 'bd-top' }, [el('span', { text: label }), el('span', { style: 'color:' + col, text: r == null ? '—' : r + '×' })]),
      el('div', { class: 'bar', style: 'position:relative' }, [el('div', { style: 'width:' + pct + '%;background:' + col }), el('span', { style: 'position:absolute;left:33.3%;top:-3px;width:1px;height:8px;background:#73736D' })]),
      sub ? el('div', { class: 'why', text: sub }) : null]);
  }
  function emptyNote(box, text) { box.appendChild(el('p', { class: 'note', text: text })); }

  function renderExtra(d) {
    var b = clear($('topics'));
    var tps = (d.topics || []);
    if (!tps.some(function (t) { return t.ratio != null; })) unavailable(b, 'topic', 'No topic data on the last scan.');
    tps.forEach(function (t) {
      var st = src('topic:' + t.name) || {};
      var sub = t.last24 != null ? t.last24 + ' articles in 24h · normal ' + t.daily_avg + '/day' + (st.state === 'stale' ? ' · ' + mins(st.age_min) + ' old' : st.state === 'cached' ? ' · updated ' + mins(st.age_min) + ' ago' : '')
        : st.state === 'skipped' ? 'waiting for its turn to refresh' : 'unavailable';
      b.appendChild(ratioBar(t.name, t.ratio, sub));
    });

    b = clear($('attention'));
    if (!(d.attention || []).length) unavailable(b, 'wikipedia', 'Wikipedia data unavailable on the last scan.');
    (d.attention || []).forEach(function (a) {
      var col = a.ratio >= 2 ? '#FF7A59' : a.ratio >= 1.3 ? '#FFB547' : '#A3A39C';
      b.appendChild(el('div', { class: 'row' }, [el('span', null, [a.article, el('span', { class: 'dim small', text: ' · ' + a.yesterday.toLocaleString() + ' views' })]),
        el('span', { class: 'v', style: 'display:flex;align-items:center;gap:12px;color:' + col }, [spark(a.series, col), (a.ratio || '—') + '×'])]));
    });

    b = clear($('statements'));
    if (!(d.statements || []).length) unavailable(b, 'feed', 'No matching official statements on the last scan.');
    else { var fn = stateNote('feed'); if (fn) b.appendChild(fn); }
    (d.statements || []).slice(0, 10).forEach(function (s) {
      var u = safeUrl(s.url);
      b.appendChild(el('div', { class: 'news', style: 'grid-template-columns:1fr' }, [el('div', null, [
        el('div', { class: 'n-meta', text: [s.source, ago(s.time), 'matched: ' + (s.matched || []).join(', ')].filter(Boolean).join(' · ') }),
        u ? el('a', { class: 'n-title', href: u, target: '_blank', rel: 'noopener noreferrer', text: s.title }) : el('span', { class: 'n-title', text: s.title })])]));
    });

    b = clear($('markets'));
    if (!(d.markets || []).length) unavailable(b, 'market', 'Market data unavailable on the last scan.');
    else { var mn = stateNote('market'); if (mn) b.appendChild(mn); }
    (d.markets || []).forEach(function (m) {
      var col = m.change_pct > 0 ? '#7FD1A5' : m.change_pct < 0 ? '#FF7A59' : '#A3A39C';
      if (m.name.indexOf('VIX') === 0) col = m.change_pct >= 15 ? '#FF7A59' : '#A3A39C';
      b.appendChild(el('div', { class: 'row' }, [el('span', { text: m.name }),
        el('span', { class: 'v', style: 'display:flex;align-items:center;gap:12px' }, [spark(m.series, col),
          el('span', { text: m.last.toLocaleString(undefined, { maximumFractionDigits: 2 }) }),
          el('span', { style: 'color:' + col, text: (m.change_pct >= 0 ? '+' : '') + m.change_pct + '%' }),
          el('span', { class: 'dim small', text: m.via || '' })])]));
    });

    b = clear($('seismic'));
    if (d.seismic == null) unavailable(b, 'seismic', 'Earthquake data unavailable.');
    else if (!d.seismic.length) emptyNote(b, 'No quakes near test sites this week.');
    (d.seismic || []).forEach(function (q) {
      var u = safeUrl(q.url);
      b.appendChild(el('div', { class: 'row' }, [el('span', null, [u ? el('a', { href: u, target: '_blank', rel: 'noopener noreferrer', text: 'M' + q.mag + ' · ' + q.site }) : 'M' + q.mag + ' · ' + q.site,
        el('span', { class: 'dim small', text: ' · ' + q.distance_km + ' km away · ' + (q.depth_km != null ? q.depth_km + ' km deep' : '') + ' · ' + ago(q.time) })]),
        el('span', { class: 'v', style: 'color:' + (q.shallow ? '#FF4D3D' : '#A3A39C'), text: q.shallow ? 'Shallow' : 'Deep' })]));
    });

    b = clear($('navwarn'));
    if (d.nav_warnings == null) unavailable(b, 'nav_warnings', 'Maritime warnings unavailable.');
    else if (!d.nav_warnings.length) emptyNote(b, 'No active missile, rocket or firing warnings among ' + (d.nav_total_active || 0) + ' active warnings.');
    (d.nav_warnings || []).slice(0, 10).forEach(function (w) {
      b.appendChild(el('div', { class: 'post' }, [el('div', { class: 'm' }, [el('span', { text: [w.id, w.authority, w.issued].filter(Boolean).join(' · ') }),
        el('span', { style: 'color:' + (w.type === 'Missile / rocket' ? '#FFB547' : '#A3A39C'), text: w.type })]), el('div', { class: 't', style: 'font-size:14px', text: w.text })]));
    });

    b = clear($('outages'));
    if (d.outages == null) unavailable(b, 'internet_outages', 'Outage data unavailable.');
    else if (!d.outages.length) emptyNote(b, 'No outages detected in watched countries.');
    (d.outages || []).forEach(function (o) {
      var col = o.score >= 1000 ? '#FF7A59' : '#A3A39C';
      b.appendChild(row(o.name + ' · ' + o.events + ' events', 'score ' + o.score.toLocaleString(), col));
    });

    b = clear($('fcdo'));
    if (!(d.fcdo || []).length) unavailable(b, 'fcdo', 'UK travel advice unavailable on the last scan.');
    (d.fcdo || []).slice(0, 10).forEach(function (f) {
      var u = safeUrl(f.url);
      b.appendChild(el('div', { class: 'row' }, [el('span', null, [u ? el('a', { href: u, target: '_blank', rel: 'noopener noreferrer', text: f.country }) : f.country,
        el('span', { class: 'dim small', text: ' · ' + ago(f.updated) + (f.change ? ' · ' + f.change : '') })]),
        el('span', { class: 'v', style: 'color:' + (f.avoid_all ? '#FF7A59' : '#A3A39C'), text: f.avoid_all ? 'Avoid all travel' : (f.alerts || []).length ? 'Partial' : 'Open' })]));
    });

    var fw = $('fires-wrap'); fw.hidden = !(d.fires || []).length;
    b = clear($('fires'));
    (d.fires || []).forEach(function (f) { b.appendChild(row(f.area, f.hotspots_24h + ' hotspots')); });

    var g = groups.seismic; g.clearLayers();
    (d.seismic || []).forEach(function (q) {
      L.circleMarker([q.lat, q.lon], { radius: 4 + (q.mag || 0) * 1.5, color: '#B48EF0', weight: 1, fillColor: q.shallow ? '#FF4D3D' : '#B48EF0', fillOpacity: 0.5 })
        .bindTooltip('M' + q.mag + ' near ' + q.site + (q.shallow ? ' (shallow)' : '')).addTo(g);
    });
  }

  var STATE_LABEL = { ok: ['Live', '#7FD1A5'], cached: ['Recent (cached)', '#A3A39C'], stale: ['Old data', '#FFB547'],
    failed: ['Failed', '#FF7A59'], not_configured: ['Not set up', '#8EB8E5'], skipped: ['Waiting', '#A3A39C'] };
  function renderDiagnostics(d) {
    var all = d.sources || {}, names = Object.keys(all).sort(function (a, b) {
      var o = { failed: 0, stale: 1, not_configured: 2, skipped: 3, cached: 4, ok: 5 };
      return (o[all[a].state] - o[all[b].state]) || a.localeCompare(b);
    });
    var counts = {};
    names.forEach(function (n) { counts[all[n].state] = (counts[all[n].state] || 0) + 1; });
    $('diag-summary').textContent = 'Data sources · ' + Object.keys(STATE_LABEL).filter(function (k) { return counts[k]; })
      .map(function (k) { return counts[k] + ' ' + STATE_LABEL[k][0].toLowerCase(); }).join(' · ') + (d.gdelt_requests_used != null ? ' · ' + d.gdelt_requests_used + ' news-API requests' : '');
    var tb = clear($('diag-rows'));
    names.forEach(function (n) {
      var st = all[n], lab = STATE_LABEL[st.state] || [st.state, '#A3A39C'];
      tb.appendChild(el('tr', null, [
        el('td', { text: n + (st.essential ? ' *' : '') }),
        el('td', { style: 'color:' + lab[1], text: lab[0] + (st.http ? ' · HTTP ' + st.http : '') }),
        el('td', { class: 'dim', text: st.last_ok ? ago(st.last_ok) : 'never' }),
        el('td', { class: 'dim diag-msg', text: st.error || st.note || (st.state === 'cached' ? 'reused, ' + mins(st.age_min) + ' old' : '') })]));
    });
  }

  function render(d) {
    state.data = d;
    renderTop(d); renderTicker(d); renderFlashpoints(d); renderSignals(d); renderNews(d);
    renderIndex(d); renderTies(d); renderExtra(d); renderGov(d); renderAircraft(d); renderSocial(d); renderDiagnostics(d);
    drawConflict(); drawAircraft();
  }

  function load() {
    fetch('data/latest.json?t=' + Date.now()).then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(render).catch(function (e) {
        $('error-bar').hidden = false;
        $('error-bar').textContent = 'Could not load data/latest.json (' + e.message + '). Has the collector run yet?';
      });
  }

  // ---------- init ----------
  var sel = $('site-sel');
  SITES.forEach(function (s, i) { sel.appendChild(el('option', { value: String(i), text: s[0] })); });
  sel.addEventListener('change', function () { state.site = Number(sel.value); });
  $('show-rings').addEventListener('click', function () { showRings(false); });
  drawToggles(); drawSites(); renderRings();
  load();
  setInterval(load, 60000);
  setInterval(function () { if (state.data) renderTop(state.data); }, 30000);
})();
