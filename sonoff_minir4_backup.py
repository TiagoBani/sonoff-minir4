#!/usr/bin/env python3
"""Read an already installed MINIR4 auxiliary and request return to stock over Wi-Fi.

Does not install firmware or send eWeLink upgrade commands.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'firmware-liberator'))
from tools.espressif.dump_stock_flash import check
from tools.espressif.analyze_vendor_ota import parse_esp_image
from sonoff_minir4_image import READOUT_VERSIONS


class AuxiliaryHTTPError(ValueError):
    def __init__(self, status):
        self.status = status
        super().__init__('Auxiliary request returned HTTP ' + str(status))


def access_token():
    header = (ROOT / 'minir4-readout/main/access.local.h').read_text(encoding='utf-8')
    match = re.search(r'^#define READOUT_ACCESS_TOKEN "([0-9a-f]{64})"$', header, re.M)
    if not match:
        raise ValueError('Readout access token missing')
    return match[1]


class Reader:
    def __init__(self, host, token, expected_mac, port=80):
        address = ipaddress.ip_address(host)
        if address.version != 4 or not address.is_private:
            raise ValueError('Expected a private local IPv4 address')
        self.host, self.port = host, port
        self.token, self.mac = token, expected_mac.lower()

    def request(self, path, method='GET', limit=4 * 1024 * 1024):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=30)
        try:
            connection.request(method, path, headers={'X-Access-Token': self.token})
            response = connection.getresponse()
            if response.status != 200:
                raise AuxiliaryHTTPError(response.status)
            body = response.read(limit + 1)
            if len(body) > limit:
                raise ValueError('Auxiliary response exceeds size limit')
            return body, response.getheader('X-Flash-Size')
        finally:
            connection.close()

    def identify(self):
        body, _ = self.request('/status', limit=4096)
        text = body.decode('ascii')
        if text.splitlines()[0] not in ['minir4 readout ' + v for v in READOUT_VERSIONS]:
            raise ValueError('Unexpected readout identity')
        if 'mac: ' + self.mac not in text.splitlines():
            raise ValueError('Readout MAC does not match the chosen module')
        return text

    def read(self):
        status = self.identify()
        flash, declared = self.request('/flash')
        if len(flash) != 4 * 1024 * 1024 or declared != str(len(flash)):
            raise ValueError('Incomplete or unexpected flash size')
        remote_hash, hash_size = self.request('/flash-sha256', limit=128)
        if hash_size != declared or remote_hash.decode('ascii').strip() != hashlib.sha256(flash).hexdigest():
            raise ValueError('Flash differs from the auxiliary SHA-256')
        efuse = None
        efuse_error = None
        try:
            efuse, _ = self.request('/efuse', limit=124)
        except AuxiliaryHTTPError as exc:
            if exc.status != 500:
                raise
            efuse_error = 'HTTP 500; eFuse readout unavailable, flash still validated separately'
        if efuse is not None and len(efuse) != 124:
            raise ValueError('Unexpected ESP32 eFuse readout length')
        report = check(flash)
        # The upstream assumes a C3 bootloader at 0; ESP32 boots at 0x1000.
        boot = parse_esp_image(flash[0x1000:0x8000])
        report['bootloader'] = {'offset': '0x1000', 'chip_id': boot['chip_id'],
                                'checksum_valid': boot['checksum_valid'],
                                'sha256_valid': boot['sha256_valid']}
        if boot['chip_id'] != 0 or not boot['checksum_valid'] or boot['sha256_valid'] is False:
            raise ValueError('Invalid ESP32 bootloader in dump')
        if not report['partition_table_md5_valid'] or report['otadata_selects'] is None:
            raise ValueError('Invalid partition table or boot selection')
        if not all(p['within_dump'] for p in report['partitions']):
            raise ValueError('Partition outside dump')
        apps = [p for p in report['partitions'] if 'image_valid' in p]
        if len(apps) != 2 or not all(p['image_valid'] for p in apps):
            raise ValueError('Expected two valid application slots')
        selected = next((p for p in apps if p['label'] == report['otadata_selects']), None)
        if not selected or (selected.get('app') or {}).get('project') != 'esp32_fw':
            raise ValueError('Next boot does not select the original Sonoff application')
        report.update({'matches_auxiliary_sha256': True,
                       'backup_before_first_write': False,
                       'efuse_sha256': hashlib.sha256(efuse).hexdigest() if efuse is not None else None,
                       'efuse_error': efuse_error,
                       'auxiliary_status': status})
        return flash, efuse, report

    def return_to_stock(self):
        self.identify()
        self.request('/return', method='POST', limit=1024)


def save(flash, efuse, report):
    output = ROOT / 'captures/minir4-readout' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output.mkdir(parents=True, mode=0o700)
    for name, data in [('flash.bin', flash), ('efuse.bin', efuse),
                       ('report.json', (json.dumps(report, indent=2) + '\n').encode())]:
        if data is None:
            continue
        fd = os.open(output / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as target:
            target.write(data)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', help='local address, defaults to target.local.json')
    parser.add_argument('--return-only', action='store_true', help='request restart into original firmware')
    parser.add_argument('--return-after-backup', action='store_true')
    args = parser.parse_args()
    config = json.loads((ROOT / 'target.local.json').read_text(encoding='utf-8'))
    reader = Reader(args.host or config['ip'], access_token(), config['mac'])
    try:
        if args.return_only:
            reader.return_to_stock()
            print('Wi-Fi return requested; firmware still needs to be confirmed online.')
            return
        flash, efuse, report = reader.read()
        output = save(flash, efuse, report)
        print('Verified post-installation backup saved privately:', output)
        if args.return_after_backup:
            reader.return_to_stock()
            print('Wi-Fi return requested; firmware still needs to be confirmed online.')
    except Exception as exc:
        # Never echo network bodies, tokens or dumps.
        print('Readout not completed. Error type:', type(exc).__name__)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
