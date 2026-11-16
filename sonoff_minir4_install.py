#!/usr/bin/env python3
"""Install the experimental MINIR4 reader, back up, and return over Wi-Fi.

Without --install, perform only read-only preflight checks. With --install,
the inactive app partition is overwritten before a backup can be obtained.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import http.client
import json
import os
from pathlib import Path
import socket
import threading
import time
import sys

from sonoff_read_only import load_credentials
from sonoff_minir4_image import validate, READOUT_VERSIONS
from sonoff_minir4_backup import Reader, access_token, save

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'firmware-liberator'))
from tools.ewelink.get_device_key import login_session, get_devices, select_device
from tools.ewelink.query_ota import ota_identity
from tools.ewelink.discover_ewelink import discover
from tools.autoflash.ewelink_lan import advert_fields, advert_state
from tools.ewelink.relay import app_socket
from tools.ewelink.websocket_minimal import WebSocketError
from tools.ewelink.ota_push import FirmwareServer


def check_device(device, config):
    identity = ota_identity(device)
    if (identity['deviceid'] != config['device_id'] or
            identity['model'] != 'SN-ESP32D0-MINIR4-01' or
            identity['version'] != '1.2.0' or not device.get('online')):
        raise ValueError('Expected the chosen MINIR4 online on stock 1.2.0')
    return identity


def check_purpose(firmware, homekit_trial):
    if homekit_trial:
        valid = any(marker in firmware for marker in (b'minir4 homekit 0.2.0',b'minir4 homekit 0.2.1',b'minir4 homekit 0.2.2'))
    else:
        valid = any(('minir4 readout ' + v).encode() in firmware for v in READOUT_VERSIONS)
    if not valid:
        raise ValueError('Firmware does not match the explicitly selected purpose')


def private_json(path, data):
    # Only this run's report is replaced; backups are written separately with O_EXCL.
    temp = path.with_suffix('.tmp')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as output:
        json.dump(data, output, indent=2)
        output.write('\n')
    temp.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--install', action='store_true')
    parser.add_argument('--homekit-trial', action='store_true',
                        help='deliver the reviewed HomeKit prototype and leave it in temporary trial; never commit')
    args = parser.parse_args()
    firmware = args.image.read_bytes()
    if hashlib.sha256(firmware).hexdigest() != args.expected_sha256:
        parser.error('Firmware differs from the reviewed SHA-256')
    image = validate(firmware)
    if image['wrapper']['header_version'] != '9.9.9':
        parser.error('Expected the reviewed experimental wrapper version')
    check_purpose(firmware, args.homekit_trial)
    config = json.loads((ROOT / 'target.local.json').read_text(encoding='utf-8'))
    if args.homekit_trial:
        from sonoff_homekit_ctl import HomeKitReader
        reader = HomeKitReader(config['ip'], access_token(), config['mac'], port=8080)
    else:
        reader = Reader(config['ip'], access_token(), config['mac'])
    credentials = load_credentials(ROOT / '.env')
    run = ROOT / 'captures/minir4-install-runs' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    run.mkdir(mode=0o700, parents=True)
    report_path = run / 'report.json'
    report = {'install_requested': args.install, 'homekit_trial_requested': args.homekit_trial,
              'command_may_have_been_sent': False,
              'command_sent': False, 'bytes_served': 0, 'backup_saved': False,
              'return_requested': False, 'stock_confirmed': False,
              'firmware_sha256': args.expected_sha256}
    private_json(report_path, report)
    server = ws = None
    thread = None
    auxiliary_seen = False
    result = 1
    try:
        region, session = login_session(credentials['EWELINK_EMAIL'], credentials['EWELINK_PASSWORD'],
                                        credentials.get('EWELINK_COUNTRY_CODE') or '+55',
                                        credentials.get('EWELINK_REGION') or 'us')
        credentials.clear()
        device = select_device(get_devices(region, session['at']), config['device_id'])
        identity = check_device(device, config)
        fields = advert_fields(discover(8, target=config['ip']), config['device_id'])
        state = advert_state(fields, device['devicekey']) if fields else None
        if not state or state.get('fwVersion') != '1.2.0':
            raise ValueError('Chosen module did not authenticate in local discovery')
        report['preflight_passed'] = True
        private_json(report_path, report)
        print('Preflight: chosen MINIR4 authenticated locally and online on stock 1.2.0.', flush=True)
        if not args.install:
            return 0
        route = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            route.connect((config['ip'], 8081))
            local_ip = route.getsockname()[0]
        finally:
            route.close()
        # Silence request-line logs, which can include device signatures.
        server = FirmwareServer((local_ip, 8088), firmware, config['ip'], say=lambda _: None, live=False)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        # Our own address must not be allowed to retrieve firmware.
        conn = http.client.HTTPConnection(local_ip, 8088, timeout=3)
        try:
            conn.request('GET', '/user1.bin')
            response = conn.getresponse()
            if response.status != 403 or response.read():
                raise ValueError('OTA source restriction preflight failed')
        finally:
            conn.close()
        ws = app_socket(region, session)
        sequence = str(int(time.time() * 1000))
        report['command_may_have_been_sent'] = True
        private_json(report_path, report)
        digest = hashlib.sha256(firmware).hexdigest()
        ws.send_json({'action': 'upgrade', 'deviceid': config['device_id'],
                      'apikey': device['apikey'], 'userAgent': 'app', 'sequence': sequence,
                      'params': {'model': identity['model'], 'version': '9.9.9',
                                 'binList': [{'name': name, 'downloadUrl': f'http://{local_ip}:8088/{name}',
                                              'digest': digest} for name in ('user1.bin', 'user2.bin')]}})
        report['command_sent'] = True
        private_json(report_path, report)
        print('Experimental readout OTA requested; serving only the chosen module.', flush=True)
        deadline = time.monotonic() + 120
        last_progress = -1
        while time.monotonic() < deadline:
            served = server.unique_bytes_served()
            progress = 100 * served // len(firmware)
            if progress != last_progress:
                print(f'Delivery coverage: {served}/{len(firmware)} bytes ({progress}%).', flush=True)
                last_progress = progress
                report['bytes_served'] = served
                private_json(report_path, report)
            if served == len(firmware):
                break
            if ws:
                try:
                    message = ws.receive_json(timeout=0.5)
                    if message.get('sequence') == sequence:
                        error = message.get('error', 0)
                        report['cloud_command_error'] = error
                        if error:
                            raise ValueError('Cloud rejected the upgrade command')
                except socket.timeout:
                    pass
                except WebSocketError:
                    ws.close()
                    ws = None
            else:
                time.sleep(0.5)
        report['bytes_served'] = server.unique_bytes_served()
        if report['bytes_served'] != len(firmware):
            raise ValueError('Firmware delivery incomplete; do not send another update automatically')
        print('All bytes served; awaiting authenticated auxiliary startup.', flush=True)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                status = reader.identify()
                auxiliary_seen = True
                if args.homekit_trial:
                    report['homekit_status'] = status
                    private_json(report_path, report)
                    if status.get('startup_failed'):
                        raise RuntimeError('HomeKit startup failed; diagnostic status saved')
                    if status.get('homekit_ready') is False:
                        time.sleep(1)
                        continue
                break
            except (OSError, ValueError, http.client.HTTPException):
                time.sleep(2)
        if not auxiliary_seen:
            raise ValueError('Auxiliary startup not observed at the chosen address')
        report['auxiliary_seen'] = True
        private_json(report_path, report)
        if args.homekit_trial:
            status = reader.identify()
            report['homekit_status'] = status
            private_json(report_path, report)
            if status.get('homekit_ready') is False or status.get('mode') != 'trial' or status.get('storage_failed') is not False or status.get('heap_free', 0) < 30000:
                raise ValueError('HomeKit trial not healthy; return to the original')
            report.update({'homekit_trial_ready': True, 'homekit_status': status,
                           'automatic_commit': False})
            private_json(report_path, report)
            print('HomeKit trial authenticated and ready; automatic commit disabled.', flush=True)
            print(json.dumps({k: status.get(k) for k in ('app','mode','paired_controllers','heap_free','heap_minimum','storage_failed')}), flush=True)
            # The owner will pair/test on the phone. Trial's own watchdog remains active.
            auxiliary_seen = False
            result = 0
            return result
        print('Auxiliary identity and MAC confirmed. Reading flash over Wi-Fi.', flush=True)
        flash, efuse, dump_report = reader.read()
        output = save(flash, efuse, dump_report)
        report.update({'backup_saved': True, 'backup_directory': str(output),
                       'backup_sha256': dump_report['sha256']})
        private_json(report_path, report)
        print('Post-installation backup verified and saved privately.', flush=True)
        reader.return_to_stock()
        report['return_requested'] = True
        private_json(report_path, report)
        auxiliary_seen = False
        print('Return to original firmware requested over Wi-Fi.', flush=True)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                fields = advert_fields(discover(4, target=config['ip']), config['device_id'])
                state = advert_state(fields, device['devicekey']) if fields else None
                cloud = select_device(get_devices(region, session['at']), config['device_id'])
                if state and state.get('fwVersion') == '1.2.0' and cloud.get('online'):
                    report.update({'stock_confirmed': True, 'version_after': '1.2.0'})
                    print('Original 1.2.0 confirmed locally and online in eWeLink.', flush=True)
                    result = 0
                    break
            except Exception:
                pass
            time.sleep(2)
    except (Exception, KeyboardInterrupt) as exc:
        report['error_type'] = type(exc).__name__
        print('Run did not complete. Error type:', type(exc).__name__, flush=True)
    finally:
        credentials.clear()
        if auxiliary_seen:
            try:
                reader.return_to_stock()
                report['return_requested'] = True
            except Exception:
                report['return_request_failed'] = True
        if ws:
            ws.close()
        if server:
            report['bytes_served'] = server.unique_bytes_served()
            server.shutdown()
            server.server_close()
        if thread:
            thread.join(timeout=3)
        private_json(report_path, report)
        print('Run report:', report_path, flush=True)
    return result


if __name__ == '__main__':
    raise SystemExit(main())
