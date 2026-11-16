"""Check actual ESP32 field positions and avoid exposing protected/key bits."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from sonoff_minir4_efuse import decode, inspect


def record(system=0, secure_version=0, key_byte=0):
    data = bytearray(124)
    data[:28] = system.to_bytes(28, 'little')
    data[28:92] = bytes([key_byte]) * 64
    data[108:112] = secure_version.to_bytes(4, 'little')
    return bytes(data)


class EFuseTests(unittest.TestCase):
    def test_disabled_security_flags(self):
        result = decode(record())
        self.assertFalse(result['secure_boot_v1_enabled'])
        self.assertFalse(result['secure_boot_v2_enabled'])
        self.assertFalse(result['flash_encryption_enabled'])
        self.assertEqual(result['secure_version_field_bits_set'], 0)
        self.assertFalse(result['bootloader_rollback_policy_proven'])

    def test_secure_boot_bits_not_confused_with_calibration_or_keys(self):
        v1 = decode(record(1 << 196, key_byte=0xFF))
        v2 = decode(record(1 << 197))
        self.assertTrue(v1['secure_boot_v1_enabled'])
        self.assertFalse(v1['secure_boot_v2_enabled'])
        self.assertFalse(v2['secure_boot_v1_enabled'])
        self.assertTrue(v2['secure_boot_v2_enabled'])

    def test_encryption_uses_parity_not_nonzero_counter(self):
        for counter, active in [(0, False), (1, True), (3, False), (7, True), (127, True)]:
            self.assertEqual(decode(record(counter << 20))['flash_encryption_enabled'], active)

    def test_protected_fields_report_unknown_not_zero(self):
        result = decode(record((12 << 16), 7))
        self.assertIsNone(result['coding_scheme'])
        self.assertIsNone(result['secure_version_field_bits_set'])

    def test_secure_version_popcount_and_coding_restriction(self):
        self.assertEqual(decode(record(0, 0x80000001))['secure_version_field_bits_set'], 2)
        self.assertIsNone(decode(record(1 << 192, 7))['secure_version_field_bits_set'])

    def test_never_reports_key_block_contents(self):
        self.assertEqual(decode(record(key_byte=0)), decode(record(key_byte=0xA5)))

    def test_reject_other_readout_formats(self):
        for size in (0, 123, 125, 128):
            with self.assertRaises(ValueError):
                decode(bytes(size))

    def test_digest_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path/'efuse.bin').write_bytes(record())
            (path/'report.json').write_text(json.dumps({'efuse_sha256': hashlib.sha256(record(1)).hexdigest()}))
            with self.assertRaisesRegex(ValueError, 'differs'):
                inspect(path/'efuse.bin', path/'report.json')


if __name__ == '__main__':
    unittest.main()
