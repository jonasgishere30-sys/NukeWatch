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
  var CAT = { command: ['Airborne command', '#FF7A59'], bomber: ['Bomber', '#FF9F5A'], tanker: ['Tanker', '#FFB547'], recon: ['Recon', '#A3A39C'] };
  var SITES = [
    ['Washington, D.C.', 38.9, -77.0], ['Offutt AFB (STRATCOM), Nebraska', 41.12, -95.91], ['Minot AFB, North Dakota', 48.42, -101.36],
    ['Malmstrom AFB, Montana', 47.5, -111.18], ['F.E. Warren AFB, Wyoming', 41.13, -104.87], ['Kings Bay sub base, Georgia', 30.8, -81.52],
    ['Kitsap-Bangor sub base, Washington', 47.73, -122.71], ['Whiteman AFB, Missouri', 38.73, -93.55], ['Barksdale AFB, Louisiana', 32.5, -93.66],
    ['Moscow', 55.75, 37.62], ['Kozelsk ICBM division, Russia', 54.03, 35.78], ['Gadzhiyevo sub base, Kola', 69.25, 33.33],
    ['Engels Air Base, Russia', 51.48, 46.2], ['Beijing', 39.9, 116.4], ['Yulin Naval Base, Hainan', 18.22, 109.55],
    ['Faslane, Scotland', 56.07, -4.82], ['Île Longue, France', 48.3, -4.52]
  ];

  var state = { data: null, fp: null, yieldKt: 300, site: 0, layers: { conflict: true, aircraft: true, sites: false } };
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
  var groups = { conflict: L.layerGroup().addTo(map), aircraft: L.layerGroup().addTo(map), sites: L.layerGroup() };
  var ringLayer = L.layerGroup().addTo(map);

  fetch('assets/countries.geojson').then(function (r) { return r.json(); }).then(function (g) {
    countriesGeo = g;
    g.features.forEach(function (f) { if (f.id != null) countryNames[String(f.id)] = f.properties.name; });
    // Neutral outline of every country, drawn under the highlights.
    L.geoJSON(g, { interactive: false, style: { color: '#3A3A36', weight: 0.6, fillColor: '#1A1A18', fillOpacity: 0.55 } }).addTo(baseLayer);
    if (state.data) { drawConflict(); renderTies(state.data); }
  });

  function drawToggles() {
    var box = clear($('layers'));
    [['conflict', 'Conflicts', '#FF4D3D'], ['aircraft', 'Aircraft', '#FFB547'], ['sites', 'Strategic sites', '#A3A39C']].forEach(function (b) {
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
      var c = RC[f.rung - 1];
      var m = L.marker([f.lat, f.lon], { title: f.name, icon: L.divIcon({ className: '', iconSize: null, iconAnchor: [10, 11],
        html: '<span class="fp-marker" style="border-color:' + c + '"><b style="background:' + c + '">' + f.rung + '</b></span>' }) });
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
    var c = LCOL[d.level - 1];
    var next = new Date(new Date(d.updated).getTime() + 15 * 60000);
    var mins = Math.max(0, Math.round((next - Date.now()) / 60000));
    $('updated').textContent = 'Updated ' + hhmm(d.updated) + ' UTC · ' + (mins > 0 ? 'next in ' + mins + ' min' : 'next scan due');
    $('foot-scan').textContent = 'Last scan ' + d.updated.slice(0, 16).replace('T', ' ') + ' UTC · ' + d.history_days + ' days of history';
    $('score').textContent = d.score;
    $('level').textContent = 'LEVEL ' + d.level + ' · ' + LEVELS[d.level - 1].toUpperCase();
    $('level').style.color = c;
    $('headline').textContent = d.summary.headline;
    $('track-fill').style.cssText = 'width:' + d.score + '%;background:' + c;
    $('track-dot').style.cssText = 'left:' + d.score + '%;background:' + c;
    $('summary-text').textContent = d.summary.text;
    var ul = clear($('changed'));
    d.summary.changed.forEach(function (x) { ul.appendChild(el('li', { text: x })); });
    var errs = Object.keys(d.errors || {});
    $('error-bar').hidden = !errs.length;
    if (errs.length) $('error-bar').textContent = 'Some sources failed on the last scan: ' + errs.join(', ') + '.';
    document.title = 'NukeWatch · ' + d.score + ' ' + LEVELS[d.level - 1];
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
    d.flashpoints.slice().sort(function (a, b) { return b.rung - a.rung || (b.stories_24h || 0) - (a.stories_24h || 0); }).forEach(function (f) {
      box.appendChild(el('button', { class: 'fp', type: 'button', 'aria-pressed': String(state.fp === f.id), onclick: function () { selectFp(f.id); } }, [
        el('span', null, [el('span', { class: 'fp-name', text: f.name }), el('span', { class: 'fp-sub', text: f.rung_name + (f.stories_24h != null ? ' · ' + f.stories_24h + ' stories/24h' : '') })]),
        el('span', { class: 'fp-r', style: 'color:' + RC[f.rung - 1], text: 'R' + f.rung + ' ' + f.trend })]));
    });
  }

  function renderSignals(d) {
    var box = clear($('signal-list'));
    var a = (d.aircraft || {}).counts || {}, g = d.gov || {}, s = d.social || {};
    var A = '#FFB547';
    function ratio(x) { return x ? x + '×' : '—'; }
    box.appendChild(row('Command aircraft airborne', String(a.command || 0)));
    box.appendChild(row('Bombers airborne', String(a.bomber || 0)));
    box.appendChild(row('Tankers airborne', String(a.tanker || 0)));
    box.appendChild(row('Nuclear-related news', ratio(d.nuclear_news_ratio), d.nuclear_news_ratio > 1.3 ? A : null));
    box.appendChild(row('Preparedness news', ratio(g.prep_ratio), g.prep_ratio > 1.3 ? A : null));
    box.appendChild(row('New Level-4 advisories (7d)', String((g.recent_level4 || []).length), (g.recent_level4 || []).length ? A : null));
    box.appendChild(row('Embassy ordered departures', String((g.ordered_departures || []).length), (g.ordered_departures || []).length ? A : null));
    box.appendChild(row('Bluesky chatter', s.bluesky_per_hour != null ? s.bluesky_per_hour + '/hr' + (s.bluesky_ratio ? ' · ' + s.bluesky_ratio + '×' : '') : 'off', s.bluesky_ratio > 1.3 ? A : null));
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
    if (!list.length) box.appendChild(el('p', { class: 'note', text: 'No stories in the last 24 hours.' }));
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
    $('pts-label').textContent = d.score;
    var bd = clear($('breakdown'));
    d.breakdown.forEach(function (b) {
      var pct = Math.min(100, b.pts / b.max * 100), col = pct >= 45 ? '#FFB547' : '#F5F5F0';
      bd.appendChild(el('div', { class: 'bd' }, [
        el('div', { class: 'bd-top' }, [el('span', { text: b.name }), el('span', { style: 'color:' + col }, [String(b.pts), el('span', { class: 'dim', text: ' / ' + b.max })])]),
        el('div', { class: 'bar' }, [el('div', { style: 'width:' + pct + '%;background:' + col })]),
        el('div', { class: 'why', text: b.why })]));
    });
    $('baseline-note').textContent = d.history_days < 3
      ? 'Confidence ' + d.confidence.toLowerCase() + ': still learning what normal looks like (' + d.history_days + ' of 3+ days). Aircraft and social baselines are not counted yet.'
      : 'Confidence ' + d.confidence.toLowerCase() + ' · ' + d.history_days + ' days of history.';
    var lv = clear($('levels'));
    LEVELS.forEach(function (n, i) {
      lv.appendChild(el('div', { class: 'lv' + (i + 1 === d.level ? ' on' : '') }, [
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
    if (!prep.length) box.appendChild(el('p', { class: 'note', text: 'No preparedness stories in the last 3 days.' }));
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
    if (!(g.level4 || []).length) l4.appendChild(el('span', { text: 'Feed unavailable' }));
    var od = clear($('ordered'));
    if (!(g.ordered_departures || []).length) od.appendChild(row('None listed', ''));
    (g.ordered_departures || []).forEach(function (a) { od.appendChild(row(a.country, a.time ? a.time.slice(0, 10) : '')); });
  }

  function renderAircraft(d) {
    var a = d.aircraft || {}, c = a.counts || {};
    $('ac-meta').textContent = (a.feed || 'feed down') + ' · command ' + (c.command || 0) + ' · bomber ' + (c.bomber || 0) + ' · tanker ' + (c.tanker || 0) + ' · recon ' + (c.recon || 0);
    var tb = clear($('ac-rows'));
    var order = ['command', 'bomber', 'tanker', 'recon'];
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
    $('soc-meta').textContent = 'Bluesky ' + (s.bluesky_per_hour != null ? s.bluesky_per_hour + ' posts/hr' : 'off') + ' · Reddit ' + (s.reddit_hits || 0) + ' matches · nothing counts until confirmed';
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

  function render(d) {
    state.data = d;
    renderTop(d); renderTicker(d); renderFlashpoints(d); renderSignals(d); renderNews(d);
    renderIndex(d); renderTies(d); renderGov(d); renderAircraft(d); renderSocial(d);
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
