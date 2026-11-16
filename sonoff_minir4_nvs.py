#!/usr/bin/env python3
"""Inspect the owner's saved MINIR4 NVS locally without printing credentials.

Uses the Espressif parser installed with the isolated PlatformIO toolchain.
No device commands, network connections or writes to the supplied dump.
"""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent


def pair_info(flash):
    parser_path = ROOT / '.platformio-minir4/packages/framework-espidf/components/nvs_flash/nvs_partition_tool'
    sys.path.insert(0, str(parser_path))
    from nvs_parser import NVS_Partition
    sys.path.insert(0, str(ROOT / 'firmware-liberator'))
    from tools.espressif.dump_stock_flash import parse_partition_table
    partitions, md5_valid = parse_partition_table(flash)
    if not md5_valid:
        raise ValueError('Invalid partition table')
    nvs = next(p for p in partitions if p['label'] == 'nvs' and p['type'] == 1 and p['subtype'] == 2)
    data = flash[nvs['offset']:nvs['offset'] + nvs['size']]
    if len(data) != nvs['size']:
        raise ValueError('Truncated NVS')
    parsed = NVS_Partition('nvs', bytearray(data))
    entries = []
    for page in parsed.pages:
        crc = page.header['crc']
        if page.header['status'] not in ('Active', 'Full') or crc['original'] != crc['computed']:
            continue
        for entry in page.entries:
            crc = entry.metadata['crc']
            if entry.state == 'Written' and crc['original'] == crc['computed']:
                entries.append((page.header['page_index'], entry.index, entry))
    entries.sort(key=lambda row: row[:2])
    namespaces = [e for _, _, e in entries if e.metadata['namespace'] == 0 and e.key == 'pair' and e.metadata['type'] == 'uint8_t']
    if len(namespaces) != 1:
        raise ValueError('Expected exactly one pair namespace')
    namespace = namespaces[0].data['value']
    records = [(seq, pos, e) for seq, pos, e in entries if e.metadata['namespace'] == namespace and e.key == 'info']
    indices = [(seq, pos, e) for seq, pos, e in records if e.metadata['type'] == 'blob_index']
    if not indices:
        raise ValueError('Expected a current pair/info blob index')
    seq, pos, index = indices[-1]
    chunks = []
    start = index.data['chunk_start']
    for chunk in range(start, start + index.data['chunk_count']):
        candidates = [e for s, p, e in records if (s, p) < (seq, pos) and e.metadata['type'] == 'blob_data' and e.metadata['chunk_index'] == chunk]
        if not candidates:
            raise ValueError('Missing pair/info chunk')
        e = candidates[-1]
        crc = e.metadata['crc']
        if crc['data_original'] != crc['data_computed'] or not all(child.state == 'Written' for child in e.children):
            raise ValueError('Invalid pair/info data CRC or entry state')
        chunks.append(bytes(b''.join(child.raw for child in e.children)[:e.data['size']]))
    blob = b''.join(chunks)
    if len(blob) != index.data['size']:
        raise ValueError('Incomplete pair/info blob')
    return blob


def inspect(dump):
    flash = dump.read_bytes()
    blob = pair_info(flash)
    with tempfile.TemporaryDirectory() as directory:
        library = Path(directory) / 'stock_wifi.dylib'
        subprocess.run(['clang', '-dynamiclib', '-Wall', '-Wextra', '-Werror',
                        str(ROOT / 'minir4-readout/main/stock_wifi.c'), '-o', str(library)], check=True)
        native = ctypes.CDLL(str(library))
        decode = native.minir4_decode_pair_wifi
        decode.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p]
        decode.restype = ctypes.c_bool
        ssid = ctypes.create_string_buffer(32)
        password = ctypes.create_string_buffer(64)
        source = ctypes.create_string_buffer(blob)
        valid = decode(source, len(blob), ssid, password)
        # Compare in memory; never emit the values or a hash of the password.
        matches = valid and ssid.raw == blob[71:104].split(b'\0')[0].ljust(32, b'\0') and password.raw == blob[104:169].split(b'\0')[0].ljust(64, b'\0')
        ctypes.memset(ssid, 0, 32)
        ctypes.memset(password, 0, 64)
        ctypes.memset(source, 0, len(blob))
    if not matches:
        raise ValueError('Unsupported Wi-Fi record layout')
    return {'dump_sha256': hashlib.sha256(flash).hexdigest(), 'pair_info_bytes': len(blob),
            'pair_info_version': 2, 'native_decoder_matches_saved_fields': True,
            'credentials_displayed': False, 'device_contacted': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dump', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(inspect(args.dump), indent=2))
