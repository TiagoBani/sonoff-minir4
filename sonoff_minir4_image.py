#!/usr/bin/env python3
"""Build/validate a MINIR4 application OTA candidate offline; never contact a device."""
import argparse
import hashlib
import json
import re
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'firmware-liberator'))
from tools.espressif.analyze_vendor_ota import analyze, parse_esp_image

MODEL = 'FWSW-E32R4-MINIR4-ESP32D0WDR2V3'
READOUT_VERSIONS = ('0.1.0', '0.1.1', '0.1.2')
# Published MINIR4 layout, not yet read from our unit.
PUBLISHED_SLOT_SIZE = 0x1F0000


def validate_payload(payload):
    image = parse_esp_image(payload)
    if image['chip_id'] != 0:
        raise ValueError('Expected classic ESP32, not ESP32-C3 or another chip')
    if not image['checksum_valid'] or image['sha256_valid'] is not True:
        raise ValueError('Invalid checksum or missing/invalid appended SHA-256')
    if image['trailing_bytes']:
        raise ValueError('Unexplained bytes after ESP32 image')
    if len(payload) > PUBLISHED_SLOT_SIZE:
        raise ValueError('Application exceeds the published MINIR4 slot size')
    if payload[2] != 2 or payload[3] != 0x20:
        raise ValueError('Expected DIO, 40 MHz, 4 MB image header')
    return image


def validate(data):
    report = analyze(data)
    wrapper = report['wrapper']
    checks = ('magic_valid', 'header_reserved_zero', 'header_crc32_valid',
              'payload_offset_valid', 'payload_size_valid', 'payload_crc32_valid',
              'record_crc32_valid', 'record_reserved_zero')
    if not all(wrapper[k] for k in checks):
        raise ValueError('Invalid Sonoff wrapper')
    if wrapper['model'] != MODEL:
        raise ValueError('Wrong MINIR4 wrapper model')
    if wrapper['header_version'] != wrapper['record_version']:
        raise ValueError('Inconsistent wrapper versions')
    if not re.fullmatch(r'\d+\.\d+\.\d+', wrapper['header_version']):
        raise ValueError('Invalid wrapper version')
    validate_payload(data[100:])
    report['deployment_validated'] = False
    report['partition_layout_source'] = 'published MINIR4 reference, not our unit'
    return report


def build(payload, template, version='9.9.9'):
    validate(template)
    validate_payload(payload)
    if not re.fullmatch(r'\d+\.\d+\.\d+', version) or len(version) >= 8:
        raise ValueError('Version must fit the eight-byte Sonoff field')
    if not any(('minir4 readout ' + version).encode() in payload for version in READOUT_VERSIONS):
        raise ValueError('Application is not the expected readout build')
    header = bytearray(template[:100])
    header[2:10] = version.encode().ljust(8, b'\0')
    header[0x38:0x48] = version.encode().ljust(16, b'\0')
    struct.pack_into('>I', header, 0x4C, len(payload))
    struct.pack_into('>I', header, 0x50, zlib.crc32(payload) & 0xFFFFFFFF)
    struct.pack_into('>I', header, 0x54, zlib.crc32(header[0x18:0x54]) & 0xFFFFFFFF)
    struct.pack_into('>I', header, 0x14, zlib.crc32(header[:0x14]) & 0xFFFFFFFF)
    wrapped = bytes(header) + payload
    validate(wrapped)
    return wrapped


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path, help='validate an existing wrapped image')
    parser.add_argument('--payload', type=Path)
    parser.add_argument('--template', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.image:
        data = args.image.read_bytes()
    elif args.payload and args.template and args.output:
        data = build(args.payload.read_bytes(), args.template.read_bytes())
        args.output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Firmware contains private access credentials; never overwrite an older build.
        import os
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as out:
            out.write(data)
    else:
        parser.error('Use --image or --payload, --template and --output')
    report = validate(data)
    print(json.dumps({'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                      'chip_id': report['esp_image']['chip_id'],
                      'model': report['wrapper']['model'], 'structure_valid': True,
                      'deployment_validated': False}, indent=2))
    print('Offline only; structural validation does not prove boot or recovery.')


if __name__ == '__main__':
    main()
