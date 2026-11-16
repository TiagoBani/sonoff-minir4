"""Reject C3 images and corrupt firmware before an experimental OTA is possible."""
import hashlib
import struct
import unittest
import zlib
from sonoff_minir4_image import MODEL, build, validate, PUBLISHED_SLOT_SIZE


def payload(chip=0):
    header = bytearray(24)
    header[0:4] = bytes([0xE9, 1, 2, 0x20])
    struct.pack_into('<H', header, 12, chip)
    header[23] = 1
    segment = b'minir4 readout 0.1.0\0'
    data = bytes(header) + struct.pack('<II', 0x3F400020, len(segment)) + segment
    checksum = 0xEF
    for byte in segment:
        checksum ^= byte
    data += b'\0' * (15 - len(data) % 16) + bytes([checksum])
    return data + hashlib.sha256(data).digest()


def template():
    app = payload()
    header = bytearray(100)
    header[:2] = b'\x03\x01'
    header[2:10] = b'1.2.0\0\0\0'
    header[0x18:0x38] = MODEL.encode().ljust(32, b'\0')
    header[0x38:0x48] = b'1.2.0'.ljust(16, b'\0')
    struct.pack_into('>III', header, 0x48, 100, len(app), zlib.crc32(app))
    struct.pack_into('>I', header, 0x54, zlib.crc32(header[0x18:0x54]))
    struct.pack_into('>I', header, 0x14, zlib.crc32(header[:20]))
    return bytes(header) + app


class FirmwareChecks(unittest.TestCase):
    def test_roundtrip(self):
        report = validate(build(payload(), template()))
        self.assertEqual(report['wrapper']['header_version'], '9.9.9')
        self.assertEqual(report['esp_image']['chip_id'], 0)
        self.assertFalse(report['deployment_validated'])

    def test_reject_c3(self):
        with self.assertRaisesRegex(ValueError, 'classic ESP32'):
            build(payload(5), template())

    def test_reject_corrupt_hash(self):
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            build(payload()[:-1] + bytes([payload()[-1] ^ 1]), template())

    def test_reject_corrupt_template(self):
        bad = bytearray(template())
        bad[0x14] ^= 1
        with self.assertRaisesRegex(ValueError, 'wrapper'):
            build(payload(), bad)

    def test_reject_wrong_model_even_with_valid_crc(self):
        bad = bytearray(template())
        bad[0x18] ^= 1
        struct.pack_into('>I', bad, 0x54, zlib.crc32(bad[0x18:0x54]))
        with self.assertRaisesRegex(ValueError, 'model'):
            build(payload(), bad)

    def test_reject_extra_bytes(self):
        with self.assertRaisesRegex(ValueError, 'Unexplained'):
            build(payload() + b'\0', template())

    def test_reject_version_overflow(self):
        with self.assertRaisesRegex(ValueError, 'Version'):
            build(payload(), template(), '999.99.99')


if __name__ == '__main__':
    unittest.main()
