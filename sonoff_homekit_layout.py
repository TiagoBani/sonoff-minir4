#!/usr/bin/env python3
"""Validate a saved MINIR4 layout and model a single-slot HomeKit design offline.

This is a design validator, not a flasher or a firmware enforcement layer.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'firmware-liberator'))
from tools.espressif.dump_stock_flash import parse_partition_table, selected_ota_slot
from tools.espressif.analyze_vendor_ota import parse_esp_image

EXPECTED = {
    'nvs': (1, 2, 0x9000, 0x10000),
    'reserve': (1, 2, 0x19000, 0x4000),
    'otadata': (1, 0, 0x1D000, 0x2000),
    'phy_init': (1, 1, 0x1F000, 0x1000),
    'ota_0': (0, 0x10, 0x20000, 0x1F0000),
    'ota_1': (0, 0x11, 0x210000, 0x1F0000),
}
STOCK_NATIVE_HASH = '3fbb2a5607aa18dac0e179fa3dc1f52772b5a7b16f9e809b5e03de74737ad54e'


def write_allowed(actor, offset, size):
    """Proposed byte ranges only. Actual firmware must enforce them separately.

    No partial writes across boundaries, no erase-all or unspecified actor.
    'stock_ota' models stock executing while it replaces the opposite slot.
    It does not express or constrain all writes performed by vendor software.
    """
    if type(offset) is not int or type(size) is not int or offset < 0 or size <= 0:
        return False
    ranges = {
        'homekit_storage': [(0x19000, 0x1D000)],
        'boot_selection': [(0x1D000, 0x1F000)],
        'stock_ota': [(0x20000, 0x210000)],
    }
    return any(start <= offset and offset + size <= end for start, end in ranges.get(actor, []))


def validate(flash):
    if len(flash) != 0x400000:
        raise ValueError('Expected the complete 4 MB flash copy')
    partitions, valid = parse_partition_table(flash)
    if not valid or len(partitions) != len(EXPECTED):
        raise ValueError('Invalid or unexpected partition table')
    actual = {p['label']: (p['type'], p['subtype'], p['offset'], p['size']) for p in partitions}
    if actual != EXPECTED or any(p['flags'] != 0 for p in partitions):
        raise ValueError('Layout differs from the reviewed MINIR4 profile')
    original = flash[0x210000:]
    image = parse_esp_image(original)
    if not image['checksum_valid'] or image['sha256_valid'] is not True or image['chip_id'] != 0:
        raise ValueError('Original Sonoff image is invalid')
    if image['stored_sha256'] != STOCK_NATIVE_HASH:
        raise ValueError('Original differs from the reviewed stock 1.2.0 image')
    if selected_ota_slot(flash[0x1D000:0x1F000], 2) != 1:
        raise ValueError('Saved boot selection does not point to the original Sonoff')
    if flash[0x19000:0x1D000] != b'\xff' * 0x4000:
        raise ValueError('Reserve contains data; do not initialize or erase it automatically')
    return {
        'profile': 'MINIR4 stock 1.2.0 / original ota_1',
        'source_dump_sha256': hashlib.sha256(flash).hexdigest(),
        'existing_partition_table_preserved': True,
        'stock_native_sha256': STOCK_NATIVE_HASH,
        'proposed_homekit_app': {'label': 'ota_0', 'offset': 0x20000, 'size': 0x1F0000},
        'preserved_stock_app': {'label': 'ota_1', 'offset': 0x210000, 'size': 0x1F0000},
        'proposed_homekit_storage': {'label': 'reserve', 'offset': 0x19000, 'size': 0x4000,
                                      'erased_in_saved_dump': True, 'initialized': False},
        'boot_selection': {'label': 'otadata', 'offset': 0x1D000, 'size': 0x2000},
        'homekit_self_ota_allowed': False,
        'planned_update_route': 'return to stock, stock OTA to ota_0, trial, explicit commit',
        'runtime_flash_policy_implemented': False,
        'homekit_implemented_or_deployed': False,
        'device_contacted': False,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dump', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(validate(args.dump.read_bytes()), indent=2))
