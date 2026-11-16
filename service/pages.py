"""HTML pages for the machine-readable routes.

Every route still answers JSON by default; these templates are served only
when the client asks for text/html. They reuse the lookup page's stylesheet
(/ui/styles.css) so the whole service shares one clinical-clarity theme.
"""
import html
import time

BRAND = ('<a class="brand" href="/ui/" aria-label="CoWIN home">'
         '<span class="brand-mark" aria-hidden="true">+</span>CoWIN</a>')
FOOTER = '<footer><span>CoWIN / Two-zone cloud deployment</span></footer>'


def _e(value):
    return html.escape(str(value), quote=True)


def _fmt_uptime(seconds):
    seconds = int(seconds)
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _fmt_timestamp(epoch):
    try:
        return time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(float(epoch)))
    except (TypeError, ValueError):
        return _e(epoch)


def _kv(rows):
    """rows: list of (label, value, mono?) tuples rendered as a key-value list."""
    items = []
    for label, value, mono in rows:
        cls = ' class="mono"' if mono else ''
        items.append(f'<div><dt>{_e(label)}</dt><dd{cls}>{_e(value)}</dd></div>')
    return '<dl class="kv">' + ''.join(items) + '</dl>'


def _status_pill(status):
    ok = status == 'healthy'
    cls = 'ok' if ok else 'bad'
    label = 'Healthy' if ok else 'Unhealthy'
    return f'<span class="status-pill {cls}">{label}</span>'


def _layout(title, eyebrow, heading, intro, content):
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="{_e(title)} - CoWIN two-zone cloud deployment.">
  <title>CoWIN | {_e(title)}</title>
  <link rel="stylesheet" href="/ui/styles.css">
</head>
<body>
  <header class="site-header">{BRAND}
    <a class="api-link" href="/ui/">Center lookup <span aria-hidden="true">&#8599;</span></a>
  </header>
  <main class="sub-page">
    <section class="page-head">
      <p class="eyebrow"><span class="tiny-dot"></span> {_e(eyebrow)}</p>
      <h1>{_e(heading)}</h1>
      <p class="intro">{_e(intro)}</p>
    </section>
    {content}
  </main>
  {FOOTER}
</body>
</html>"""


def info_page(data):
    served_by = data.get('served_by', {})
    runtime = data.get('runtime_metrics', {})
    endpoints = data.get('endpoints', {})
    descriptions = {
        '/health': 'Health check used by the load balancer target group',
        '/api/v1/centers': 'List centers; filter with ?district= or ?pincode=',
        '/api/v1/centers?pincode=380009': 'Lookup filtered by pincode',
        '/api/v1/centers?district=Ahmedabad': 'Lookup filtered by district',
        '/metrics': 'Operational counters for monitoring',
    }
    rows = ''.join(
        '<tr><td class="mono"><a href="{0}">{1}</a></td><td>{2}</td></tr>'.format(
            _e(path), _e(path), _e(descriptions.get(path, 'Endpoint')))
        for path in endpoints.values())
    content = f"""
    <section class="panel">
      <h2>Service</h2>
      <div class="kv-with-pill">
        <dl class="kv">
          <div><dt>Name</dt><dd>{_e(data.get('service', ''))}</dd></div>
          <div><dt>Theme</dt><dd>{_e(data.get('theme', ''))}</dd></div>
        </dl>
        <p class="pill-row">Status {_status_pill(data.get('status', ''))}</p>
      </div>
    </section>
    <section class="panel">
      <h2>Served by</h2>
      {_kv([
        ('Availability zone', served_by.get('availability_zone', ''), True),
        ('Instance', served_by.get('instance_id', ''), True),
        ('Hostname', served_by.get('hostname', ''), True),
        ('Uptime', _fmt_uptime(runtime.get('uptime_seconds', 0)), False),
        ('Total requests served', runtime.get('total_requests_served', ''), False),
      ])}
    </section>
    <section class="panel">
      <h2>Endpoint directory</h2>
      <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th scope="col">Endpoint</th><th scope="col">What it does</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
      </div>
      <p class="page-actions"><a href="/ui/">Open the center lookup page</a></p>
    </section>"""
    return _layout('API info', 'SERVICE INFORMATION',
                   'Service information',
                   'What this instance is, where it is running, and the endpoints it serves.',
                   content)


def health_page(data, status_code):
    status = data.get('status', '')
    rows = [
        ('Availability zone', data.get('zone', ''), True),
        ('Instance', data.get('instance_id', ''), True),
        ('Checked at', _fmt_timestamp(data.get('timestamp', '')), True),
    ]
    if status_code == 200:
        rows.insert(2, ('Uptime', _fmt_uptime(data.get('uptime_seconds', 0)), False))
        rows.insert(3, ('Total requests served', data.get('total_requests_served', ''), False))
        note = 'This instance is passing its health checks.'
    else:
        rows.insert(0, ('Reason', data.get('reason', ''), False))
        note = 'This instance is currently failing its health checks.'
    content = f"""
    <section class="panel status-panel">
      <p class="pill-row">Current status {_status_pill(status)}</p>
      <p class="muted-note">{_e(note)}</p>
      {_kv(rows)}
    </section>
    <p class="page-actions"><a href="/info">Service information</a><a href="/metrics">Metrics</a></p>"""
    return _layout('Health check', 'LOAD BALANCER TARGET HEALTH',
                   'Health status',
                   'The check the load balancer runs against this instance.',
                   content)


def _center_card(center):
    district = center.get('district_name') or 'District not listed'
    fee = center.get('fee_type') or 'Fee not listed'
    name = center.get('name') or 'Unnamed center'
    address = center.get('address') or 'Address not listed'
    location = ' / '.join(str(part) for part in
                          [center.get('state_name'), center.get('pincode')] if part)
    start = str(center.get('from_time') or '')[:5] or 'Not listed'
    end = str(center.get('to_time') or '')[:5] or 'Not listed'
    sessions = []
    for session in center.get('sessions') or []:
        vaccine = session.get('vaccine') or 'Vaccine not listed'
        age = session.get('min_age_limit')
        age = '?' if age is None else age
        date = session.get('date') or 'Date not listed'
        capacity = session.get('available_capacity')
        capacity = 'Not listed' if capacity is None else capacity
        sessions.append(
            f'<div class="session"><div class="session-top"><span>{_e(vaccine)}</span>'
            f'<span>{_e(age)}+ years</span></div>'
            f'<span class="session-detail">{_e(date)} &middot; Available capacity: '
            f'{_e(capacity)}</span></div>')
    sessions_html = ''.join(sessions) or '<p class="session-detail">No sessions listed.</p>'
    return (f'<article class="center-card"><div class="card-top">'
            f'<span class="district-tag">{_e(district)}</span>'
            f'<span class="fee-tag">{_e(fee)}</span></div>'
            f'<h3>{_e(name)}</h3><p class="address">{_e(address)}</p>'
            f'<p class="location">{_e(location)}</p>'
            f'<div class="center-hours">Hours: {_e(start)} - {_e(end)}</div>'
            f'<div class="sessions">{sessions_html}</div>'
            f'</article>')


def centers_page(data, filters):
    served_by = data.get('served_by', {})
    centers = data.get('centers') or []
    count = data.get('count', len(centers))
    filter_bits = []
    if filters.get('district'):
        filter_bits.append(f'district &ldquo;{_e(filters["district"])}&rdquo;')
    if filters.get('pincode') is not None:
        filter_bits.append(f'pincode {_e(filters["pincode"])}')
    scope = 'Filtered by ' + ' and '.join(filter_bits) if filter_bits else 'No filters applied'
    summary = _kv([
        ('Matching centers', count, False),
        ('Availability zone', served_by.get('zone', ''), True),
        ('Instance', served_by.get('instance_id', ''), True),
    ])
    if centers:
        cards = ''.join(_center_card(center) for center in centers)
        results = f'<div class="center-grid">{cards}</div>'
    else:
        results = ('<div class="empty-state"><span class="empty-icon" aria-hidden="true">'
                   '&#8981;</span><h3>No centers found</h3>'
                   '<p>Try a different district or pincode.</p></div>')
    content = f"""
    <section class="panel">
      <h2>Query</h2>
      <p class="muted-note">{scope}.</p>
      {summary}
    </section>
    {results}
    <p class="page-actions"><a href="/ui/">Search with the interactive lookup</a></p>"""
    return _layout('Center lookup results', 'API RESPONSE',
                   f'{count} ' + ('center' if count == 1 else 'centers'),
                   'The centers this response returned, rendered as a page.',
                   content)


def metrics_page(data):
    limiter = data.get('rate_limit', {})
    store = data.get('store', {})
    auth = data.get('auth', {})
    by_endpoint = data.get('requests_by_endpoint', {})
    by_status = data.get('responses_by_status', {})
    endpoint_rows = ''.join(
        f'<tr><td class="mono">{_e(path)}</td><td class="num">{_e(count)}</td></tr>'
        for path, count in sorted(by_endpoint.items()))
    status_rows = ''.join(
        f'<tr><td class="mono">{_e(code)}</td><td class="num">{_e(count)}</td></tr>'
        for code, count in sorted(by_status.items()))
    content = f"""
    <section class="panel">
      <h2>Instance</h2>
      <div class="kv-with-pill">
        <dl class="kv">
          <div><dt>Availability zone</dt><dd class="mono">{_e(data.get('zone', ''))}</dd></div>
          <div><dt>Instance</dt><dd class="mono">{_e(data.get('instance_id', ''))}</dd></div>
          <div><dt>Uptime</dt><dd>{_e(_fmt_uptime(data.get('uptime_seconds', 0)))}</dd></div>
          <div><dt>Total requests served</dt><dd>{_e(data.get('total_requests_served', ''))}</dd></div>
        </dl>
        <p class="pill-row">Status {_status_pill(data.get('status', ''))}</p>
      </div>
    </section>
    <section class="panel">
      <h2>Requests by endpoint</h2>
      <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th scope="col">Endpoint</th><th scope="col">Requests</th></tr></thead>
        <tbody>{endpoint_rows or '<tr><td colspan="2">No requests recorded yet.</td></tr>'}</tbody>
      </table>
      </div>
    </section>
    <section class="panel">
      <h2>Responses by status</h2>
      <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th scope="col">Status</th><th scope="col">Responses</th></tr></thead>
        <tbody>{status_rows or '<tr><td colspan="2">No responses recorded yet.</td></tr>'}</tbody>
      </table>
      </div>
    </section>
    <section class="panel">
      <h2>Configuration</h2>
      {_kv([
        ('Store backend', store.get('backend', ''), False),
        ('Centers loaded', store.get('centers_loaded', ''), False),
        ('API key required', 'Yes' if auth.get('enabled') else 'No', False),
        ('Failed auth attempts', auth.get('failed_attempts', ''), False),
        ('Rate limiting', 'On' if limiter.get('enabled') else 'Off', False),
        ('Rejected requests', limiter.get('rejected_requests', 0), False),
        ('Rate limit', f"{limiter.get('requests_per_second', '')} req/s, "
                       f"burst {limiter.get('burst', '')}", False),
      ])}
    </section>
    <p class="page-actions"><a href="/info">Service information</a><a href="/health">Health status</a></p>"""
    return _layout('Metrics', 'OPERATIONAL COUNTERS',
                   'Metrics',
                   'Operational counters for this instance since it started.',
                   content)


def not_found_page(path):
    content = f"""
    <section class="panel">
      <div class="empty-state empty-state-plain">
        <span class="empty-icon" aria-hidden="true">&#8981;</span>
        <h3>Nothing at <span class="mono">{_e(path)}</span></h3>
        <p>That path is not an endpoint on this service.</p>
      </div>
      <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th scope="col">Valid endpoint</th><th scope="col">What it does</th></tr></thead>
        <tbody>
          <tr><td class="mono"><a href="/ui/">/ui/</a></td><td>The interactive center lookup page</td></tr>
          <tr><td class="mono"><a href="/health">/health</a></td><td>Health check used by the load balancer</td></tr>
          <tr><td class="mono"><a href="/api/v1/centers">/api/v1/centers</a></td><td>List centers; filter with ?district= or ?pincode=</td></tr>
          <tr><td class="mono"><a href="/metrics">/metrics</a></td><td>Operational counters for monitoring</td></tr>
          <tr><td class="mono"><a href="/info">/info</a></td><td>Service information and endpoint directory</td></tr>
        </tbody>
      </table>
      </div>
    </section>"""
    return _layout('Page not found', 'ERROR 404',
                   'Page not found',
                   'The page or endpoint you asked for does not exist here.',
                   content)


def error_page(data, status_code):
    content = ('<section class="panel"><h2>' + _e(data.get('error', 'Request failed')) +
               '</h2><p>' + _e(data.get('message', 'Please try again.')) +
               '</p><p class="page-actions"><a href="/ui/">Return to center lookup</a></p></section>')
    return _layout('Request failed', f'HTTP {status_code}', 'Request failed',
                   'The service could not complete this request.', content)
