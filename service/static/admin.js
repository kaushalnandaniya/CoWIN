/* Admin console: polls the local two-zone topology and drives the
   /simulate/fail and /simulate/recover controls. Same-origin-safe, no
   dependencies, no polling data leaves the configured endpoints. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const DEFAULTS = { alb: 'http://localhost:8080', a: 'http://localhost:8081', b: 'http://localhost:8082' };
  const STORE_KEY = 'cowin-admin-endpoints';
  const POLL_MS = 1500;
  const SPARK_LEN = 30;

  let cfg = loadConfig();
  let apiKey = '';
  let timer = null;
  const state = { a: 'unknown', b: 'unknown', alb: 'unknown', serving: null };
  const latencyHistory = { a: [], b: [] };

  function loadConfig() {
    const params = new URLSearchParams(location.search);
    let stored = {};
    try { stored = JSON.parse(localStorage.getItem(STORE_KEY) || '{}'); } catch (e) { stored = {}; }
    const clean = value => (value || '').trim().replace(/\/+$/, '');
    return {
      alb: clean(params.get('alb')) || clean(stored.alb) || DEFAULTS.alb,
      a: clean(params.get('a')) || clean(stored.a) || DEFAULTS.a,
      b: clean(params.get('b')) || clean(stored.b) || DEFAULTS.b,
    };
  }

  function saveConfig() {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(cfg)); } catch (e) { /* private mode */ }
  }

  function log(message, kind) {
    const item = document.createElement('li');
    if (kind) item.className = kind;
    const time = document.createElement('span');
    time.className = 'log-time';
    time.textContent = new Date().toLocaleTimeString([], { hour12: false });
    item.append(time, document.createTextNode(message));
    const list = $('event-log');
    list.prepend(item);
    while (list.childElementCount > 30) list.lastElementChild.remove();
  }

  async function probe(baseUrl, path) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 3000);
    const started = performance.now();
    try {
      const response = await fetch(baseUrl + path, { cache: 'no-store', signal: controller.signal });
      let data = null;
      try { data = await response.json(); } catch (e) { data = null; }
      return { reachable: true, status: response.status, data, ms: performance.now() - started };
    } catch (error) {
      return { reachable: false, status: 0, data: null, ms: performance.now() - started };
    } finally {
      clearTimeout(timeout);
    }
  }

  function fmtUptime(seconds) {
    const s = Math.floor(Number(seconds) || 0);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
    if (h) return `${h}h ${m}m ${s % 60}s`;
    if (m) return `${m}m ${s % 60}s`;
    return `${s}s`;
  }

  function setNode(id, cls, stateEl, text) {
    const node = $(id);
    const changed = !node.classList.contains(cls);
    node.classList.remove('node-ok', 'node-bad', 'node-down', 'node-unknown', 'node-idle', 'node-just-changed');
    node.classList.add(cls);
    if (changed) {
      node.classList.add('node-just-changed');
      setTimeout(() => node.classList.remove('node-just-changed'), 700);
    }
    stateEl.textContent = text;
  }

  function renderZone(prefix, zoneState, probeResult) {
    const g = $('node-' + prefix);
    const stateEl = $('zone-' + prefix + '-state');
    if (zoneState === 'ok') setNode('node-' + prefix, 'node-ok', stateEl, 'healthy');
    else if (zoneState === 'bad') setNode('node-' + prefix, 'node-bad', stateEl, 'health failing');
    else setNode('node-' + prefix, 'node-down', stateEl, 'unreachable');

    $('stat-' + prefix + '-status').textContent =
      zoneState === 'ok' ? 'Healthy' : zoneState === 'bad' ? 'Failing health checks' : 'Unreachable';
    if (probeResult.reachable && probeResult.data) {
      $('stat-' + prefix + '-instance').textContent = probeResult.data.instance_id || '-';
      $('stat-' + prefix + '-uptime').textContent = fmtUptime(probeResult.data.uptime_seconds);
      $('stat-' + prefix + '-requests').textContent =
        probeResult.data.total_requests_served != null ? String(probeResult.data.total_requests_served) : '-';
    } else {
      $('stat-' + prefix + '-instance').textContent = '-';
      $('stat-' + prefix + '-uptime').textContent = '-';
      $('stat-' + prefix + '-requests').textContent = '-';
    }

    const history = latencyHistory[prefix];
    history.push(probeResult.reachable ? Math.round(probeResult.ms) : null);
    while (history.length > SPARK_LEN) history.shift();
    $('stat-' + prefix + '-latency').textContent = probeResult.reachable ? Math.round(probeResult.ms) + ' ms' : '-';
    renderSpark(prefix, history, zoneState);
    return g;
  }

  function renderSpark(prefix, history, zoneState) {
    const line = $('spark-' + prefix + '-line');
    const values = history.filter(v => v != null);
    $('stats-' + prefix).classList.toggle('spark-bad', zoneState !== 'ok');
    if (values.length < 2) { line.setAttribute('points', ''); return; }
    const max = Math.max(...values, 1);
    const min = Math.min(...values);
    const span = Math.max(max - min, 1);
    const step = 120 / (SPARK_LEN - 1);
    const points = history.map((v, i) => {
      if (v == null) return null;
      const y = 25 - ((v - min) / span) * 21;
      return `${(i * step).toFixed(1)},${y.toFixed(1)}`;
    }).filter(Boolean).join(' ');
    line.setAttribute('points', points);
  }

  function spawnDot(pathId) {
    const path = $(pathId);
    if (!path) return;
    const length = path.getTotalLength();
    const dot = document.createElementNS(SVG_NS, 'circle');
    dot.setAttribute('r', '4');
    dot.setAttribute('class', 'dot');
    $('dots').append(dot);
    const started = performance.now();
    const DURATION = 850;
    const step = now => {
      const t = (now - started) / DURATION;
      if (t >= 1 || !dot.isConnected) { dot.remove(); return; }
      const point = path.getPointAtLength(t * length);
      dot.setAttribute('cx', point.x.toFixed(1));
      dot.setAttribute('cy', point.y.toFixed(1));
      dot.setAttribute('opacity', t < 0.85 ? '1' : String((1 - t) / 0.15));
      requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  function render() {
    renderZone('a', state.a, state.aProbe || { reachable: false, ms: 0 });
    renderZone('b', state.b, state.bProbe || { reachable: false, ms: 0 });

    const albState = $('alb-state');
    const albNode = $('node-alb');
    albNode.classList.remove('node-ok', 'node-bad', 'node-down', 'node-unknown', 'node-idle');
    if (state.alb === 'ok') {
      albNode.classList.add('node-ok');
      albState.textContent = state.serving ? `routing to ${state.serving}` : 'routing';
    } else {
      albNode.classList.add('node-down');
      albState.textContent = 'unreachable';
    }

    $('flow-client-alb').classList.toggle('flow-on', state.alb === 'ok');
    $('flow-alb-a').classList.toggle('flow-on', state.alb === 'ok' && state.serving === zoneName('a'));
    $('flow-alb-b').classList.toggle('flow-on', state.alb === 'ok' && state.serving === zoneName('b'));

    if (state.alb === 'ok') {
      spawnDot('flow-client-alb');
      if (state.serving === zoneName('a')) spawnDot('flow-alb-a');
      if (state.serving === zoneName('b')) spawnDot('flow-alb-b');
    }

    $('poll-state').textContent = 'Live - updated ' + new Date().toLocaleTimeString([], { hour12: false });
  }

  function zoneName(prefix) {
    return ($('zone-' + prefix + '-name').textContent || '').trim();
  }

  let lastServingLogged = null;

  function flashPath(pathId) {
    const path = $(pathId);
    path.classList.add('flow-flash');
    setTimeout(() => path.classList.remove('flow-flash'), 2500);
  }

  function noteTransitions(prev) {
    if (prev.a !== state.a) {
      if (state.a === 'bad') log('Zone A started failing health checks', 'log-bad');
      if (state.a === 'ok' && prev.a !== 'unknown') log('Zone A is healthy again', 'log-ok');
      if (state.a === 'down') log('Zone A unreachable', 'log-bad');
    }
    if (prev.b !== state.b) {
      if (state.b === 'bad') log('Zone B started failing health checks', 'log-bad');
      if (state.b === 'ok' && prev.b !== 'unknown') log('Zone B is healthy again', 'log-ok');
      if (state.b === 'down') log('Zone B unreachable', 'log-bad');
    }
    // Round robin flips the answering zone every request, so only announce
    // the serving zone once it has been stable across two consecutive polls
    // - that is the failover signal worth seeing, and it gets the flash.
    if (state.serving && state.serving === prev.serving && state.serving !== lastServingLogged) {
      const isFailover = lastServingLogged !== null;
      lastServingLogged = state.serving;
      log(`Load balancer is routing to ${state.serving}`, 'log-ok');
      if (isFailover) {
        flashPath(state.serving === zoneName('a') ? 'flow-alb-a' : 'flow-alb-b');
      }
    }
    if (prev.alb !== state.alb && state.alb !== 'ok') log('Load balancer unreachable', 'log-bad');
  }

  async function poll() {
    const prev = { a: state.a, b: state.b, alb: state.alb, serving: state.serving };
    const [a, b, alb] = await Promise.all([
      probe(cfg.a, '/health'), probe(cfg.b, '/health'), probe(cfg.alb, '/health'),
    ]);
    state.aProbe = a; state.bProbe = b;
    state.a = !a.reachable ? 'down' : a.status === 200 ? 'ok' : 'bad';
    state.b = !b.reachable ? 'down' : b.status === 200 ? 'ok' : 'bad';
    state.alb = alb.reachable && alb.status === 200 ? 'ok' : 'down';
    state.serving = state.alb === 'ok' && alb.data && alb.data.zone ? alb.data.zone : null;
    if (alb.reachable && alb.data && alb.data.zone) {
      // Learn the real zone names from whichever node answered.
      for (const prefix of ['a', 'b']) {
        const probeResult = prefix === 'a' ? a : b;
        if (probeResult.reachable && probeResult.data && probeResult.data.zone) {
          $('zone-' + prefix + '-name').textContent = probeResult.data.zone;
        }
      }
    }
    noteTransitions(prev);
    render();
  }

  async function control(zoneLetter, action, label) {
    const result = $('control-result');
    result.className = 'control-result';
    result.textContent = label + '...';
    for (const id of ['btn-stop', 'btn-recover', 'btn-stop-b', 'btn-recover-b']) $(id).disabled = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    try {
      // Direct-to-node control: each zone's command goes to that zone's
      // own endpoint (locally the node itself, on AWS an SSH tunnel
      // forward - the ALB denies /simulate/* with 403 by design), so the
      // drill can only reach the intended zone. The zone-pinned path
      // lets the node double-check the letter before acting.
      const headers = {};
      if (apiKey) headers['X-API-Key'] = apiKey;
      const nodeBase = zoneLetter === 'a' ? cfg.a : cfg.b;
      const response = await fetch(`${nodeBase}/simulate/zone-${zoneLetter}/${action}`, { method: 'POST', headers, signal: controller.signal });
      if (response.ok) {
        result.textContent = label + ': command accepted.';
        result.classList.add('ok');
        log(label + ': command accepted by Zone ' + zoneLetter.toUpperCase(), 'log-ok');
        if (action === 'fail') log('Auto-recover is armed: the zone restores itself after about 2 minutes even without Recover', 'log-ok');
      } else if (response.status === 401) {
        result.textContent = label + ': rejected - the API key is missing or wrong.';
        result.classList.add('err');
        log(label + ': 401 unauthorized (check the API key)', 'log-bad');
      } else if (response.status === 409) {
        result.textContent = label + ': refused - the other zone is not healthy.';
        result.classList.add('err');
        log(label + ': 409 refused (safety interlock)', 'log-bad');
      } else {
        result.textContent = `${label}: HTTP ${response.status}.`;
        result.classList.add('err');
        log(`${label}: HTTP ${response.status}`, 'log-bad');
      }
    } catch (error) {
      result.textContent = label + ': could not reach the zone ' + zoneLetter.toUpperCase() + ' node (is the SSH tunnel up?).';
      result.classList.add('err');
      log(label + ': zone ' + zoneLetter.toUpperCase() + ' node unreachable', 'log-bad');
    } finally {
      clearTimeout(timeout);
      for (const id of ['btn-stop', 'btn-recover', 'btn-stop-b', 'btn-recover-b']) $(id).disabled = false;
      poll();
    }
  }

  function applyConfig() {
    const clean = value => (value || '').trim().replace(/\/+$/, '');
    cfg = {
      alb: clean($('cfg-alb').value) || DEFAULTS.alb,
      a: clean($('cfg-a').value) || DEFAULTS.a,
      b: clean($('cfg-b').value) || DEFAULTS.b,
    };
    saveConfig();
    log('Endpoints updated: ALB ' + cfg.alb + ', A ' + cfg.a + ', B ' + cfg.b);
    poll();
  }

  $('cfg-alb').value = cfg.alb;
  $('cfg-a').value = cfg.a;
  $('cfg-b').value = cfg.b;
  $('cfg-apply').addEventListener('click', applyConfig);
  $('api-key').addEventListener('input', event => { apiKey = event.target.value; });
  $('btn-stop').addEventListener('click', () => control('a', 'fail', 'Stop Zone A'));
  $('btn-recover').addEventListener('click', () => control('a', 'recover', 'Recover Zone A'));
  $('btn-stop-b').addEventListener('click', () => control('b', 'fail', 'Stop Zone B'));
  $('btn-recover-b').addEventListener('click', () => control('b', 'recover', 'Recover Zone B'));

  poll();
  timer = setInterval(poll, POLL_MS);
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      clearInterval(timer);
      timer = null;
    } else if (!timer) {
      poll();
      timer = setInterval(poll, POLL_MS);
    }
  });
})();
