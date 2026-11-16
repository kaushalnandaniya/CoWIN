"""HTTP coverage for the dependency-free, same-origin frontend."""
import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app


class TestFrontend(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = app.create_server(app.ServiceConfig(host='127.0.0.1', port=0,
                                      db_file=':memory:', api_key='test-key'))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_address[1]}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def request(self, path):
        try:
            return urllib.request.urlopen(self.base + path, timeout=5)
        except urllib.error.HTTPError as error:
            return error

    def test_html_aliases(self):
        for path in ['/ui', '/ui/', '/ui/index.html', '/ui/?district=test']:
            with self.subTest(path=path), self.request(path) as response:
                body = response.read().decode()
                self.assertEqual(response.status, 200)
                self.assertIn('text/html', response.headers['Content-Type'])
                self.assertIn('role="status"', body)
                self.assertIn('/ui/app.js', body)
                self.assertIn('X-Served-By-Zone', response.headers)
                self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
                self.assertIn("default-src 'self'", response.headers['Content-Security-Policy'])
                self.assertEqual(int(response.headers['Content-Length']), len(body.encode()))

    def test_assets(self):
        for path, mime in [('/ui/styles.css', 'text/css'), ('/ui/app.js', 'text/javascript')]:
            with self.subTest(path=path), self.request(path) as response:
                self.assertEqual(response.status, 200)
                self.assertIn(mime, response.headers['Content-Type'])
                self.assertGreater(len(response.read()), 100)

    def test_shared_typography_has_no_remote_font_dependency(self):
        with self.request('/ui/styles.css') as response:
            css = response.read().decode()
        self.assertIn('--sans:Arial,Helvetica,sans-serif;', css)
        self.assertIn('font-family:var(--sans)', css)
        self.assertIn('font:inherit', css)
        self.assertNotIn('@import', css)
        self.assertNotIn('fonts.googleapis.com', css)
        for path in ['/ui/', '/info', '/health', '/api/v1/centers', '/metrics', '/missing']:
            with self.subTest(path=path), self.html_request(path) as response:
                body = response.read().decode()
                self.assertIn('href="/ui/styles.css"', body)
                self.assertNotIn('fonts.googleapis.com', body)

    def test_no_filesystem_fallback(self):
        for path in ['/ui/../app.py', '/ui/%2e%2e/app.py', '/ui/centers_data.json',
                     '/ui/unknown.js', '/ui//styles.css']:
            with self.subTest(path=path), self.request(path) as response:
                self.assertEqual(response.status, 404)
                self.assertEqual(json.load(response)['error'], 'Not Found')

    def test_missing_assets_return_503(self):
        with patch.object(app, 'STATIC_DIR', '/nonexistent-cowin-static'):
            with self.request('/ui/') as response:
                self.assertEqual(response.status, 503)
                self.assertEqual(json.load(response)['error'], 'Frontend not installed')

    def test_json_contracts_preserved(self):
        for path in ['/', '/info', '/health', '/api/v1/centers']:
            with self.subTest(path=path), self.request(path) as response:
                self.assertEqual(response.status, 200)
                self.assertIn('application/json', response.headers['Content-Type'])
                self.assertIsInstance(json.load(response), dict)

    def test_frontend_does_not_include_failure_controls_or_keys(self):
        with self.request('/ui/app.js') as response:
            script = response.read().decode()
            self.assertNotIn('/simulate/', script)
            self.assertNotIn('X-API-Key', script)
            self.assertNotIn('innerHTML', script)
            self.assertIn('/api/v1/centers', script)
            self.assertNotIn('setInterval', script)


    def html_request(self, path, accept='text/html'):
        request = urllib.request.Request(self.base + path, headers={'Accept': accept})
        try:
            return urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            return error

    def test_browser_pages_and_aliases(self):
        for path, heading in [('/', 'Service information'), ('/info', 'Endpoint directory'),
                              ('/health', 'Health status'), ('/metrics', 'Operational counters'),
                              ('/api/v1/centers', 'Matching centers'), ('/centers', 'Matching centers')]:
            with self.subTest(path=path), self.html_request(path) as response:
                body = response.read().decode()
                self.assertEqual(response.status, 200)
                self.assertIn('text/html', response.headers['Content-Type'])
                self.assertEqual(response.headers['Vary'], 'Accept')
                self.assertIn(heading, body)
                self.assertIn('/ui/styles.css', body)
                self.assertIn('CoWIN / Two-zone cloud deployment', body)
                self.assertNotIn('Sample data', body)
                self.assertNotIn('NOT LIVE AVAILABILITY', body)
                self.assertEqual(int(response.headers['Content-Length']), len(body.encode()))
                self.assertIn("default-src 'self'", response.headers['Content-Security-Policy'])

    def test_html_errors_keep_http_status_and_escape_input(self):
        for path, code in [('/missing', 404), ('/api/v1/centers?pincode=no', 400)]:
            with self.subTest(path=path), self.html_request(path) as response:
                self.assertEqual(response.status, code)
                self.assertIn('text/html', response.headers['Content-Type'])
        import pages
        attack = '<script>alert(1)</script>'
        for page in [pages.not_found_page(attack), pages.error_page({'message': attack}, 400),
                     pages.centers_page({'centers': [{'name': attack}]}, {'district': attack})]:
            self.assertNotIn(attack, page)
            self.assertIn('&lt;script&gt;', page)

    def test_html_unhealthy_keeps_500(self):
        self.server.state.set_unhealthy(True)
        try:
            with self.html_request('/health') as response:
                self.assertEqual(response.status, 500)
                self.assertIn('Unhealthy', response.read().decode())
        finally:
            self.server.state.set_unhealthy(False)

    def test_accept_negotiation_preserves_json(self):
        for accept in ['*/*', 'application/json', 'text/html;q=0',
                       'text/html;q=.2,application/json;q=.9', 'text/html;q=oops']:
            with self.subTest(accept=accept), self.html_request('/info', accept) as response:
                self.assertIn('application/json', response.headers['Content-Type'])
                self.assertIn('endpoints', json.load(response))
        with self.html_request('/info', 'text/html,application/xhtml+xml,*/*;q=.8') as response:
            self.assertIn('text/html', response.headers['Content-Type'])

    def test_html_filters_and_empty_results(self):
        with self.html_request('/api/v1/centers?district=Nowheregarh') as response:
            body = response.read().decode()
            self.assertIn('No centers found', body)
            self.assertIn('Nowheregarh', body)
        with self.html_request('/api/v1/centers?pincode=380009') as response:
            self.assertIn('pincode 380009', response.read().decode())


if __name__ == '__main__':
    unittest.main()
