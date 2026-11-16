import hashlib
import http.client
import http.server
from pathlib import Path
import tempfile
import threading
import unittest

from sonoff_capture import CaptureServer, fetch_image


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data = b'example-test-image-not-real-firmware'
        self.calls = []
        self.entries = {'/ota/test/user1.bin': {
            'name': 'user1.bin', 'digest': hashlib.sha256(self.data).hexdigest()}}
        def fetcher(origin, path, request_headers=None):
            self.calls.append(path)
            return 200, self.data
        self.server = CaptureServer(('127.0.0.1', 0),
            origin=('http', '192.0.2.20', 8088), entries=self.entries,
            device_id='example-owned-device', sources=['127.0.0.1'],
            output=Path(self.temp.name), fetcher=fetcher)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, *, path=None, method='GET', source_id='example-owned-device', host='192.0.2.20:8088', agent='itead-device'):
        path = path or '/ota/test/user1.bin?deviceid=' + source_id + '&ts=123&sign=' + 'a' * 64
        c = http.client.HTTPConnection(*self.server.server_address, timeout=2)
        try:
            c.request(method, path, headers={'Host': host, 'User-Agent': agent, 'Range': 'bytes=0-23'})
            r = c.getresponse()
            return r.status, r.getheader('Content-Length'), r.read()
        finally:
            c.close()

    def test_success_saves_but_returns_zero_bytes(self):
        self.assertEqual(self.request(), (502, '0', b''))
        self.assertEqual((Path(self.temp.name) / 'user1.bin').read_bytes(), self.data)
        self.assertEqual(self.server.records[0]['outcome'], 'verified_file_saved')
        self.assertNotIn('sign', str(self.server.records))

    def test_wrong_digest_never_saves_or_relays(self):
        self.entries['/ota/test/user1.bin']['digest'] = '0' * 64
        self.assertEqual(self.request(), (502, '0', b''))
        self.assertFalse((Path(self.temp.name) / 'user1.bin').exists())

    def test_bad_identity_does_not_contact_vendor(self):
        self.assertEqual(self.request(source_id='another-device'), (502, '0', b''))
        self.assertEqual(self.calls, [])

    def test_wrong_host_does_not_contact_vendor(self):
        self.assertEqual(self.request(host='other.invalid'), (502, '0', b''))
        self.assertEqual(self.calls, [])

    def test_url_pointing_directly_at_mac_is_accepted(self):
        local_host = ':'.join(map(str, self.server.server_address))
        self.assertEqual(self.request(host=local_host), (502, '0', b''))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual((Path(self.temp.name) / 'user1.bin').read_bytes(), self.data)

    def test_different_device_agent_is_forwarded_without_logging(self):
        observed = []
        def fetcher(origin, path, headers):
            observed.append(headers.get('User-Agent'))
            return 200, self.data
        self.server.fetcher = fetcher
        self.assertEqual(self.request(agent='Example-MINIR4-Agent'), (502, '0', b''))
        self.assertEqual(observed, ['Example-MINIR4-Agent'])
        self.assertNotIn('Example-MINIR4-Agent', str(self.server.records))

    def test_absolute_url_is_rejected(self):
        self.assertEqual(self.request(path='http://elsewhere.invalid/ota/test/user1.bin'), (502, '0', b''))
        self.assertEqual(self.calls, [])

    def test_post_never_contacts_vendor(self):
        self.assertEqual(self.request(method='POST'), (405, '0', b''))
        self.assertEqual(self.calls, [])

    def test_exception_never_sends_body_or_secrets(self):
        def fail(*args):
            raise RuntimeError('example-secret-do-not-log')
        self.server.fetcher = fail
        self.assertEqual(self.request(), (502, '0', b''))
        self.assertNotIn('example-secret', str(self.server.records))

    def test_existing_file_is_not_overwritten(self):
        target = Path(self.temp.name) / 'user1.bin'
        target.write_bytes(b'preserve-existing')
        self.assertEqual(self.request(), (502, '0', b''))
        self.assertEqual(target.read_bytes(), b'preserve-existing')

    def test_attempt_limit(self):
        self.server.max_attempts = 1
        self.request()
        self.request()
        self.assertEqual(len(self.calls), 1)

    def test_sibling_download_stays_on_manifest_and_never_relays(self):
        self.entries['/ota/test/user2.bin'] = {
            'name': 'user2.bin', 'digest': hashlib.sha256(self.data).hexdigest()}
        self.server.fetch_siblings = True
        self.assertEqual(self.request(), (502, '0', b''))
        self.assertEqual(len(self.calls), 2)
        self.assertTrue(self.calls[1].startswith('/ota/test/user2.bin?'))
        self.assertEqual((Path(self.temp.name) / 'user2.bin').read_bytes(), self.data)


class VendorDownloadTests(unittest.TestCase):
    def setUp(self):
        self.body = b'fake-image-for-loopback-test'
        self.mode = 'complete'
        owner = self
        class Vendor(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                if owner.mode == 'denied':
                    self.send_response(400)
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                data = owner.body if owner.mode == 'complete' else owner.body[:4]
                self.send_response(206)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Content-Range', f'bytes 0-{len(data)-1}/{len(owner.body)}')
                self.end_headers()
                self.wfile.write(data)
        self.vendor = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Vendor)
        self.thread = threading.Thread(target=self.vendor.serve_forever, daemon=True)
        self.thread.start()
        self.origin = ('http', *self.vendor.server_address)

    def tearDown(self):
        self.vendor.shutdown()
        self.vendor.server_close()
        self.thread.join()

    def test_complete_range_is_accepted(self):
        self.assertEqual(fetch_image(self.origin, '/test'), (206, self.body))

    def test_incomplete_range_is_rejected(self):
        self.mode = 'partial'
        with self.assertRaises(ValueError):
            fetch_image(self.origin, '/test')

    def test_vendor_denial_has_no_payload(self):
        self.mode = 'denied'
        self.assertEqual(fetch_image(self.origin, '/test'), (400, None))


if __name__ == '__main__':
    unittest.main()
