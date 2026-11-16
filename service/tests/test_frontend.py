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
                self.assertIn('Sample data. Not a booking service.', body)
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


if __name__ == '__main__':
    unittest.main()
