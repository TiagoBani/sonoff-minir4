"""Exercise device identity, dump integrity and Wi-Fi return without real hardware."""
import hashlib
import struct
import unittest
import zlib
from sonoff_minir4_backup import Reader, AuxiliaryHTTPError

MAC = '12:34:56:ab:cd:ef'


def app(project):
    header = bytearray(24)
    header[:4] = bytes([0xE9, 1, 2, 0x20])
    header[23] = 1
    segment = bytearray(256)
    struct.pack_into('<I', segment, 0, 0xABCD5432)
    segment[16:21] = b'1.2.0'
    segment[48:48 + len(project)] = project.encode()
    image = bytes(header) + struct.pack('<II', 0x3F400020, len(segment)) + segment
    checksum = 0xEF
    for byte in segment:
        checksum ^= byte
    image += b'\0' * (15 - len(image) % 16) + bytes([checksum])
    return image + hashlib.sha256(image).digest()


def flash_fixture():
    flash = bytearray(b'\xff' * (4 * 1024 * 1024))
    boot = app('bootloader')
    flash[0x1000:0x1000 + len(boot)] = boot
    table = b''.join(struct.pack('<HBBII16sI', 0x50AA, typ, sub, offset, size,
                                label.encode().ljust(16, b'\0'), 0)
                     for typ, sub, offset, size, label in [
                         (1, 0, 0x1D000, 0x2000, 'otadata'),
                         (0, 0x10, 0x20000, 0x1F0000, 'ota_0'),
                         (0, 0x11, 0x210000, 0x1F0000, 'ota_1')])
    table += b'\xeb\xeb' + b'\xff' * 14 + hashlib.md5(table).digest()
    flash[0x8000:0x8000 + len(table)] = table
    seq = struct.pack('<I', 1)
    flash[0x1D000:0x1D004] = seq
    struct.pack_into('<II', flash, 0x1D000 + 24, 2, zlib.crc32(seq, 0xFFFFFFFF))
    for offset, project in [(0x20000, 'esp32_fw'), (0x210000, 'minir4_readout')]:
        image = app(project)
        flash[offset:offset + len(image)] = image
    return bytes(flash)


class FakeReader(Reader):
    def __init__(self):
        super().__init__('127.0.0.1', 'fake-token', MAC)
        flash = flash_fixture()
        self.calls = []
        self.responses = {
            '/status': (('minir4 readout 0.1.0\nmac: ' + MAC + '\n').encode(), None),
            '/flash': (flash, str(len(flash))),
            '/flash-sha256': (hashlib.sha256(flash).hexdigest().encode(), str(len(flash))),
            '/efuse': (bytes(124), None),
            '/return': (b'Restarting', None),
        }

    def request(self, path, method='GET', limit=4 * 1024 * 1024):
        self.calls.append((method, path))
        return self.responses[path]


class BackupChecks(unittest.TestCase):
    def test_valid_esp32_dump_and_original_boot(self):
        reader = FakeReader()
        flash, _, report = reader.read()
        self.assertEqual(len(flash), 4 * 1024 * 1024)
        self.assertEqual(report['bootloader']['offset'], '0x1000')
        self.assertEqual(report['otadata_selects'], 'ota_0')
        self.assertTrue(report['matches_auxiliary_sha256'])
        self.assertFalse(report['backup_before_first_write'])
        self.assertNotIn(('POST', '/return'), reader.calls)

    def test_reject_wrong_device_before_read_or_return(self):
        for operation in ('read', 'return_to_stock'):
            reader = FakeReader()
            reader.mac = '12:34:56:00:00:00'
            with self.assertRaisesRegex(ValueError, 'MAC'):
                getattr(reader, operation)()
            self.assertEqual(reader.calls, [('GET', '/status')])

    def test_reject_incomplete_flash(self):
        reader = FakeReader()
        flash, size = reader.responses['/flash']
        reader.responses['/flash'] = (flash[:-1], size)
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            reader.read()

    def test_reject_hash_mismatch(self):
        reader = FakeReader()
        _, size = reader.responses['/flash-sha256']
        reader.responses['/flash-sha256'] = (b'0' * 64, size)
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            reader.read()

    def test_reject_booting_auxiliary_instead_of_original(self):
        reader = FakeReader()
        flash = bytearray(reader.responses['/flash'][0])
        seq = struct.pack('<I', 2)
        flash[0x1D000:0x1D004] = seq
        struct.pack_into('<II', flash, 0x1D000 + 24, 2, zlib.crc32(seq, 0xFFFFFFFF))
        reader.responses['/flash'] = (bytes(flash), str(len(flash)))
        reader.responses['/flash-sha256'] = (hashlib.sha256(flash).hexdigest().encode(), str(len(flash)))
        with self.assertRaisesRegex(ValueError, 'original Sonoff'):
            reader.read()

    def test_wifi_return_checks_identity_then_posts(self):
        reader = FakeReader()
        reader.return_to_stock()
        self.assertEqual(reader.calls, [('GET', '/status'), ('POST', '/return')])

    def test_efuse_500_does_not_discard_verified_flash(self):
        reader = FakeReader()
        original_request = reader.request
        def request(path, **kwargs):
            if path == '/efuse':
                raise AuxiliaryHTTPError(500)
            return original_request(path, **kwargs)
        reader.request = request
        flash, efuse, report = reader.read()
        self.assertEqual(len(flash), 4194304)
        self.assertIsNone(efuse)
        self.assertTrue(report['matches_auxiliary_sha256'])
        self.assertIn('HTTP 500', report['efuse_error'])


if __name__ == '__main__':
    unittest.main()
