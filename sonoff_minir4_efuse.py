#!/usr/bin/env python3
"""Decode only non-secret security flags from the saved ESP32 eFuse readout.

No serial, network, eFuse programming or raw register/key output.
Offsets match ESP-IDF 5.3.1's components/efuse/esp32/esp_efuse_table.csv.
"""
import argparse
import hashlib
import json
from pathlib import Path


def decode(data):
    # Our reader serializes 7 BLK0 words and 8 words from each other block.
    if len(data) != 124:
        raise ValueError('Expected the classic ESP32 124-byte register readout')
    system = int.from_bytes(data[:28], 'little')
    read_disable = (system >> 16) & 15
    write_disable = system & 0xFFFF
    crypt_count = (system >> 20) & 127
    protected_config = bool(read_disable & 8)
    coding = None if protected_config else (system >> 192) & 3
    secure_version = None
    if not (read_disable & 4) and coding in (0, 3):
        # BLK3 starts after 28 + 32 + 32 bytes; secure version is bits 128..159.
        secure_version = int.from_bytes(data[108:112], 'little').bit_count()
    return {
        'readout_format': 'classic ESP32; BLK0 7 words; BLK1/2/3 8 words each',
        'secure_boot_v1_enabled': bool((system >> 196) & 1),
        'secure_boot_v2_enabled': bool((system >> 197) & 1),
        'flash_encryption_enabled': bool(crypt_count.bit_count() % 2),
        'flash_encryption_counter_bits_set': crypt_count.bit_count(),
        'flash_encryption_counter_write_protected': bool(write_disable & (1 << 2)),
        'uart_download_disabled': bool((system >> 27) & 1),
        'jtag_disabled': bool((system >> 198) & 1),
        'uart_download_encryption_disabled': bool((system >> 199) & 1),
        'uart_download_decryption_disabled': bool((system >> 200) & 1),
        'uart_download_cache_disabled': bool((system >> 201) & 1),
        'block1_read_protected': bool(read_disable & 1),
        'block2_read_protected': bool(read_disable & 2),
        'block3_read_protected': bool(read_disable & 4),
        'config_fields_read_protected': protected_config,
        'coding_scheme': coding,
        'secure_version_field_bits_set': secure_version,
        'bootloader_rollback_policy_proven': False,
        'raw_registers_or_keys_disclosed': False,
        'efuses_modified': False,
    }


def inspect(efuse_path, report_path):
    data = efuse_path.read_bytes()
    report = json.loads(report_path.read_text(encoding='utf-8'))
    if not report.get('efuse_sha256') or hashlib.sha256(data).hexdigest() != report['efuse_sha256']:
        raise ValueError('eFuse readout differs from the saved backup report')
    result = decode(data)
    result['integrity_matches_backup_report'] = True
    result['device_contacted'] = False
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--efuse', type=Path, required=True)
    parser.add_argument('--backup-report', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(inspect(args.efuse, args.backup_report), indent=2))
