/* Admin console: polls the local two-zone topology and drives the
   /simulate/fail and /simulate/recover controls. Same-origin-safe, no
   dependencies, no polling data leaves the configured endpoints. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const DEFAULTS = { alb: 'http://localhost:8080', a: 'http://localhost:8081', b: 'http://localhost:8082' };
  const STORE_KEY = 'cowin-admin-endpoints';
  const POLL_MS = 1500;

  let cfg = loadConfig();
  let apiKey = '';
  let timer = null;
  const state = { a: 'unknown', b: 'unknown', alb: 'unknown', serving: null };

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
    try {
      const response = await fetch(baseUrl + path, { cache: 'no-store', signal: controller.signal });
      let data = null;
      try { data = await response.json(); } catch (e) { data = null; }
      return { reachable: true, status: response.status, data };
    } catch (error) {
      return { reachable: false, status: 0, data: null };
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
    node.classList.remove('node-ok', 'node-bad', 'node-down', 'node-unknown', 'node-idle');
    node.classList.add(cls);
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
    return g;
  }

  function render() {
    renderZone('a', state.a, state.aProbe || { reachable: false });
    renderZone('b', state.b, state.bProbe || { reachable: false });

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

    $('poll-state').textContent = 'Live - updated ' + new Date().toLocaleTimeString([], { hour12: false });
  }

  function zoneName(prefix) {
    return ($('zone-' + prefix + '-name').textContent || '').trim();
  }

  let lastServingLogged = null;

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
    // Round robin flips the answering zone every request, so only log the
    // serving zone once it has been stable across two consecutive polls -
    // that is the failover signal worth seeing.
    if (state.serving && state.serving === prev.serving && state.serving !== lastServingLogged) {
      lastServingLogged = state.serving;
      log(`Load balancer is routing to ${state.serving}`, 'log-ok');
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

  async function control(path, label) {
    const result = $('control-result');
    result.className = 'control-result';
    result.textContent = label + '...';
    for (const id of ['btn-stop', 'btn-recover']) $(id).disabled = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    try {
      const headers = {};
      if (apiKey) headers['X-API-Key'] = apiKey;
      const response = await fetch(cfg.a + path, { method: 'POST', headers, signal: controller.signal });
      if (response.ok) {
        result.textContent = label + ': command accepted.';
        result.classList.add('ok');
        log(label + ': command accepted by Zone A', 'log-ok');
      } else if (response.status === 401) {
        result.textContent = label + ': rejected - the API key is missing or wrong.';
        result.classList.add('err');
        log(label + ': 401 unauthorized (check the API key)', 'log-bad');
      } else {
        result.textContent = `${label}: HTTP ${response.status}.`;
        result.classList.add('err');
        log(`${label}: HTTP ${response.status}`, 'log-bad');
      }
    } catch (error) {
      result.textContent = label + ': could not reach the Zone A node.';
      result.classList.add('err');
      log(label + ': Zone A node unreachable', 'log-bad');
    } finally {
      clearTimeout(timeout);
      for (const id of ['btn-stop', 'btn-recover']) $(id).disabled = false;
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
  $('btn-stop').addEventListener('click', () => control('/simulate/fail', 'Stop Zone A'));
  $('btn-recover').addEventListener('click', () => control('/simulate/recover', 'Recover Zone A'));

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
