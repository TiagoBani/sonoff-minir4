"""Reject corrupt/incomplete NVS before interpreting saved Wi-Fi fields."""
import struct
import unittest
import zlib
import hashlib
from sonoff_minir4_nvs import pair_info
import test_minir4_stock_wifi as wifi_test


def fixture():
    blob = bytes(wifi_test.StockWifiTests.record())
    flash = bytearray(b'\xff' * 0x19000)
    table = struct.pack('<HBBII16sI', 0x50AA, 1, 2, 0x9000, 0x10000, b'nvs'.ljust(16, b'\0'), 0)
    table += b'\xeb\xeb' + b'\xff' * 14 + hashlib.md5(table).digest()
    flash[0x8000:0x8000 + len(table)] = table
    page = bytearray(b'\xff' * 4096)
    struct.pack_into('<II', page, 0, 0xFFFFFFFE, 0)
    page[8] = 0xFE
    struct.pack_into('<I', page, 28, zlib.crc32(page[4:28], 0xFFFFFFFF))
    def entry(index, ns, kind, span, chunk, key, data):
        raw = bytearray(struct.pack('<BBBBI16s8s', ns, kind, span, chunk, 0, key.encode().ljust(16, b'\0'), data))
        struct.pack_into('<I', raw, 4, zlib.crc32(raw[:4] + raw[8:], 0xFFFFFFFF))
        page[64 + index * 32:96 + index * 32] = raw
        for i in range(index, index + span):
            page[32 + i // 4] &= ~(1 << ((i % 4) * 2))
    entry(0, 0, 1, 1, 0xFF, 'pair', b'\x01' + b'\xff' * 7)
    entry(1, 1, 0x42, 7, 0, 'info', struct.pack('<H2sI', len(blob), b'\xff\xff', zlib.crc32(blob, 0xFFFFFFFF)))
    page[128:128 + len(blob)] = blob
    entry(8, 1, 0x48, 1, 0xFF, 'info', struct.pack('<IBB2s', len(blob), 1, 0, b'\xff\xff'))
    flash[0x9000:0xA000] = page
    return flash, blob


class NVSChecks(unittest.TestCase):
    def test_valid_v2_blob_with_page_entry_and_data_crcs(self):
        flash, blob = fixture()
        self.assertEqual(pair_info(flash), blob)

    def test_corrupt_blob_data_rejected(self):
        flash, _ = fixture()
        flash[0x9000 + 128 + 105] ^= 1
        with self.assertRaisesRegex(ValueError, 'CRC'):
            pair_info(flash)

    def test_corrupt_index_rejected(self):
        flash, _ = fixture()
        flash[0x9000 + 64 + 8 * 32 + 24] ^= 1
        with self.assertRaisesRegex(ValueError, 'index'):
            pair_info(flash)

    def test_erased_payload_rejected(self):
        flash, _ = fixture()
        # Mark a child entry erased while retaining its bytes in the raw dump.
        flash[0x9000 + 32] &= ~(3 << 4)
        with self.assertRaisesRegex(ValueError, 'entry state'):
            pair_info(flash)


if __name__ == '__main__':
    unittest.main()
