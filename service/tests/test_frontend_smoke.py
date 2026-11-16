"""Browser-behavior smoke test for the lookup UI, driven in headless Chrome.

The HTTP tests in test_frontend.py only see strings. This suite runs the
real page in headless Chrome against the real service and drives the key
flows the page depends on: initial load, district and pincode filters, the
no-match empty state, inline pincode validation, and error + retry.

It needs a Chrome/Chromium binary; on machines without one it skips.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app

CHROME = next((b for b in ('google-chrome', 'google-chrome-stable', 'chromium',
                           'chromium-browser') if shutil.which(b)), None)

SMOKE_HTML = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>CoWIN UI smoke test</title></head>
<body><pre id="smoke-out">running</pre><script src="/ui/__smoke.js"></script></body>
</html>
"""

# The harness pulls the real index.html over HTTP, imports its body, loads
# the real app.js against it, then drives the form. Expected counts are
# templated in from the live API so the test tracks the sample dataset.
SMOKE_JS = r"""
(async () => {
  const out = [];
  const ok = (name, cond) => out.push((cond ? 'PASS' : 'FAIL') + ' ' + name);
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const waitFor = async (fn, timeout = 8000) => {
    const start = Date.now();
    while (Date.now() - start < timeout) {
      if (fn()) return true;
      await sleep(50);
    }
    return false;
  };
  try {
    const html = await (await fetch('/ui/')).text();
    const doc = new DOMParser().parseFromString(html, 'text/html');
    for (const node of [...doc.body.children]) document.body.append(document.importNode(node, true));
    await new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = '/ui/app.js';
      script.onload = resolve;
      script.onerror = () => reject(new Error('app.js failed to load'));
      document.body.append(script);
    });
    const $ = id => document.getElementById(id);
    const cards = () => $('centers').childElementCount;

    ok('initial load lists all __TOTAL__ centers',
       await waitFor(() => cards() === __TOTAL__) &&
       $('result-count').textContent === '__TOTAL__ centers');

    $('district').value = 'Ahmedabad';
    $('search-button').click();
    ok('district filter narrows results and announces the count',
       await waitFor(() => cards() === __DISTRICT_COUNT__) &&
       $('status').textContent.includes('__DISTRICT_COUNT__ centers'));

    $('district').value = '';
    $('pincode').value = '__PINCODE__';
    $('search-button').click();
    ok('pincode filter narrows results',
       await waitFor(() => cards() === __PINCODE_COUNT__) &&
       $('status').textContent.includes('pincode __PINCODE__'));

    $('pincode').value = '';
    $('district').value = 'Nowheregarh';
    $('search-button').click();
    ok('no match shows the empty state',
       await waitFor(() => !$('empty').hidden && cards() === 0));

    $('district').value = '';
    $('pincode').value = '012345';
    const statusBefore = $('status').textContent;
    $('search-button').click();
    await sleep(300);
    ok('invalid pincode shows an inline message and sends no request',
       !$('pincode-error').hidden &&
       $('pincode-error').textContent.includes('6-digit') &&
       $('status').textContent === statusBefore);

    $('pincode').value = '__PINCODE__';
    $('pincode').dispatchEvent(new Event('input', { bubbles: true }));
    ok('correcting the pincode clears the inline message', $('pincode-error').hidden);
    $('pincode').value = '';

    const realFetch = window.fetch;
    window.fetch = () => Promise.reject(new TypeError('offline'));
    $('district').value = 'Ahmedabad';
    $('search-button').click();
    ok('a failed lookup shows the error box with a retry button',
       await waitFor(() => !$('error').hidden));
    window.fetch = realFetch;
    $('retry-button').click();
    ok('retry restores results after a failure',
       await waitFor(() => cards() === __DISTRICT_COUNT__ && $('error').hidden));
  } catch (error) {
    out.push('FAIL harness exception: ' + error.message);
  }
  const failed = out.some(line => line.startsWith('FAIL'));
  out.push('SMOKE RESULT: ' + (failed ? 'FAIL' : 'PASS'));
  document.getElementById('smoke-out').textContent = out.join('\n');
  document.title = 'SMOKE DONE';
})();
"""

SMOKE_FILES = {
    '/ui/__smoke.html': ('__smoke.html', 'text/html; charset=utf-8'),
    '/ui/__smoke.js': ('__smoke.js', 'text/javascript; charset=utf-8'),
}


@unittest.skipUnless(CHROME, 'no Chrome/Chromium binary available for the UI smoke test')
class TestFrontendSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = app.create_server(app.ServiceConfig(host='127.0.0.1', port=0,
                                      db_file=':memory:', api_key='test-key'))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_address[1]}'

        with urllib.request.urlopen(cls.base + '/api/v1/centers', timeout=5) as response:
            centers = json.load(response)['centers']
        district_count = sum(1 for c in centers if c.get('district_name') == 'Ahmedabad')
        pincode = next(c['pincode'] for c in centers if c.get('district_name') == 'Ahmedabad')
        pincode_count = sum(1 for c in centers if c.get('pincode') == pincode)
        cls.harness_js = (SMOKE_JS
                          .replace('__TOTAL__', str(len(centers)))
                          .replace('__DISTRICT_COUNT__', str(district_count))
                          .replace('__PINCODE__', str(pincode))
                          .replace('__PINCODE_COUNT__', str(pincode_count)))

        cls.static_patch = patch.dict(app.STATIC_FILES, SMOKE_FILES)
        cls.static_patch.start()
        with open(os.path.join(app.STATIC_DIR, '__smoke.html'), 'w') as handle:
            handle.write(SMOKE_HTML)
        with open(os.path.join(app.STATIC_DIR, '__smoke.js'), 'w') as handle:
            handle.write(cls.harness_js)

    @classmethod
    def tearDownClass(cls):
        cls.static_patch.stop()
        for _, (filename, _) in SMOKE_FILES.items():
            try:
                os.remove(os.path.join(app.STATIC_DIR, filename))
            except OSError:
                pass
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def test_key_lookup_flows_in_a_real_browser(self):
        with tempfile.TemporaryDirectory() as profile:
            proc = subprocess.run(
                [CHROME, '--headless=new', '--disable-gpu', '--disable-dev-shm-usage',
                 '--no-sandbox', f'--user-data-dir={profile}',
                 '--virtual-time-budget=30000', '--dump-dom',
                 self.base + '/ui/__smoke.html'],
                capture_output=True, text=True, timeout=90)
        dom = proc.stdout
        report = ''
        match = re.search(r'<pre id="smoke-out">(.*?)</pre>', dom, re.S)
        if match:
            report = match.group(1)
        self.assertIn('SMOKE RESULT: PASS', dom,
                      msg=f'browser smoke test failed; harness report:\n{report}\n'
                          f'stderr tail: {proc.stderr[-500:]}')


if __name__ == '__main__':
    unittest.main()
