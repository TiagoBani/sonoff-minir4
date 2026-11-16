"""Run the actual portable C parser against malformed and boundary credentials."""
import ctypes
import sys
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent


class StockWifiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        library = Path(cls.temp.name) / 'stock_wifi.dylib'
        subprocess.run(['clang', ('-dynamiclib' if sys.platform=='darwin' else '-shared'), '-fPIC', '-Wall', '-Wextra', '-Werror',
                        str(ROOT / 'minir4-readout/main/stock_wifi.c'), '-o', str(library)], check=True)
        cls.library = ctypes.CDLL(str(library))
        cls.decode = cls.library.minir4_decode_pair_wifi
        cls.decode.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p]
        cls.decode.restype = ctypes.c_bool

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @staticmethod
    def record(ssid=b'Test network', password=b'fictional-password'):
        blob = bytearray(176)
        blob[:4] = b'\xaa\x55\x02\0'
        # The unrelated field must never be mistaken for the Wi-Fi password.
        blob[6:14] = b'not-wifi'
        blob[71:71 + len(ssid)] = ssid
        blob[104:104 + len(password)] = password
        return blob

    def parse(self, blob):
        ssid, password = ctypes.create_string_buffer(b'x' * 32, 32), ctypes.create_string_buffer(b'x' * 64, 64)
        source = ctypes.create_string_buffer(bytes(blob))
        ok = self.decode(source, len(blob), ssid, password)
        return ok, ssid.raw, password.raw

    def test_offsets_and_output_padding(self):
        ok, ssid, password = self.parse(self.record())
        self.assertTrue(ok)
        self.assertEqual(ssid.rstrip(b'\0'), b'Test network')
        self.assertEqual(password.rstrip(b'\0'), b'fictional-password')

    def test_maximum_lengths_without_overflow(self):
        ok, ssid, password = self.parse(self.record(b'S' * 32, b'a' * 64))
        self.assertTrue(ok)
        self.assertEqual(ssid, b'S' * 32)
        self.assertEqual(password, b'a' * 64)

    def test_open_network_and_non_ascii_ssid(self):
        ok, ssid, password = self.parse(self.record('Rede escritório'.encode(), b''))
        self.assertTrue(ok)
        self.assertEqual(ssid.rstrip(b'\0'), 'Rede escritório'.encode())
        self.assertEqual(password, bytes(64))

    def test_empty_ssid_rejected_and_outputs_cleared(self):
        self.assertEqual(self.parse(self.record(b'')), (False, bytes(32), bytes(64)))

    def test_unterminated_fields_rejected(self):
        for start, length in [(71, 33), (104, 65)]:
            blob = self.record()
            blob[start:start + length] = b'x' * length
            self.assertEqual(self.parse(blob), (False, bytes(32), bytes(64)))

    def test_unknown_versions_and_magic_rejected(self):
        for index in range(4):
            blob = self.record()
            blob[index] ^= 1
            self.assertEqual(self.parse(blob), (False, bytes(32), bytes(64)))

    def test_truncation_and_extra_bytes_rejected(self):
        for blob in (b'', self.record()[:-1], self.record() + b'\0'):
            self.assertEqual(self.parse(blob), (False, bytes(32), bytes(64)))


if __name__ == '__main__':
    unittest.main()
