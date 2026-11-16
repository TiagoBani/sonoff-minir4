#!/usr/bin/env python3
"""Ask one owned MINIR4 to contact a capture-only Mac endpoint.

The only body ever returned to the module is empty. May enter OTA mode.
Never invokes the firmware-serving or flashing functions of the reference tool.
"""
import http.client
import argparse
from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path
import socket
import sys
import threading
import time
import urllib.parse


def write_report(path, report):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600),
                   'w', encoding='utf-8') as output:
        json.dump(report, output, indent=2)
        output.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--announced-version', default='1.2.0',
                        help='version announced in capture-only OTA request; no image is served')
    args = parser.parse_args()
    if not re.fullmatch(r'\d+\.\d+\.\d+', args.announced_version):
        parser.error('Use a numeric three-component version')
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    from sonoff_read_only import load_credentials
    from sonoff_capture import CaptureServer, load_manifest
    sys.path.insert(0, str(root / 'firmware-liberator'))
    from tools.ewelink.get_device_key import login_session, get_devices, select_device
    from tools.ewelink.query_ota import ota_identity, query_ota
    from tools.ewelink.relay import app_socket
    from tools.ewelink.websocket_minimal import WebSocketError
    from archive.tools.download_ota import ota_files, private_json

    config = json.loads((root / 'target.local.json').read_text(encoding='utf-8'))
    credentials = load_credentials(root / '.env')
    server = None
    ws = None
    report = {'command_sent': False, 'firmware_bytes_served_to_device': 0, 'cloud_events': []}
    report['announced_version'] = args.announced_version
    output = root / 'firmware-oficial' / 'MINIR4' / '1.2.0'
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    report_path = output / 'capture-runs' / (run_id + '.json')
    report_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        region, session = login_session(credentials['EWELINK_EMAIL'], credentials['EWELINK_PASSWORD'],
                                        credentials.get('EWELINK_COUNTRY_CODE') or '+55',
                                        credentials.get('EWELINK_REGION') or 'us')
        credentials.clear()
        device = select_device(get_devices(region, session['at']), config['device_id'])
        identity = ota_identity(device)
        if identity['model'] != 'SN-ESP32D0-MINIR4-01' or identity['version'] != '1.2.0':
            raise ValueError('Unexpected model or version')
        if not device.get('online'):
            raise ValueError('Module offline')
        report['version_before'] = identity['version']
        query = dict(identity, version='1.1.0')
        metadata = query_ota(region, session['at'], query)
        version, files = ota_files({'response': metadata}, version='1.2.0')
        manifest = output / 'manifest.private.json'
        private_json(manifest, {'version': version, 'files': files})
        origin, entries = load_manifest(manifest)
        routing = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            routing.connect((config['ip'], 8081))
            local_ip = routing.getsockname()[0]
        finally:
            routing.close()
        server = CaptureServer((local_ip, 8088), origin=origin, entries=entries,
                               device_id=config['device_id'], sources=[config['ip']],
                               output=output)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        # Prove an actual request to the bound server returns an empty failure.
        connection = http.client.HTTPConnection(local_ip, 8088, timeout=3)
        try:
            connection.request('GET', '/__empty_response_preflight__')
            response = connection.getresponse()
            body = response.read()
            if response.status != 502 or response.getheader('Content-Length') != '0' or body:
                raise ValueError('Capture server preflight failed')
        finally:
            connection.close()
        with server.lock:
            server.records.clear()
        report['empty_response_preflight_passed'] = True
        local_files = []
        for item in files:
            url = urllib.parse.urlsplit(item['downloadUrl'])
            local_files.append({'name': item['name'], 'digest': item['digest'],
                                'downloadUrl': urllib.parse.urlunsplit(
                                    ('http', f'{local_ip}:8088', url.path, url.query, ''))})
        ws = app_socket(region, session)
        sequence = str(int(time.time() * 1000))
        ws.send_json({'action': 'upgrade', 'deviceid': config['device_id'],
                      'apikey': device['apikey'], 'userAgent': 'app', 'sequence': sequence,
                      'params': {'model': identity['model'], 'version': args.announced_version, 'binList': local_files}})
        report['command_sent'] = True
        print('Captura iniciada: URLs locais; servidor devolve somente erro vazio.', flush=True)
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            try:
                message = ws.receive_json(timeout=0.5)
                if message.get('sequence') == sequence:
                    report['cloud_events'].append({'matching_command_response': True,
                                                   'error': message.get('error')})
            except socket.timeout:
                pass
            except WebSocketError:
                report['cloud_socket_closed'] = True
                break
            with server.lock:
                saved = any(r.get('outcome') == 'verified_file_saved' for r in server.records)
                exhausted = len(server.records) >= server.max_attempts
            if saved or exhausted:
                break
        # Read-only account status after the attempt; no recovery command.
        try:
            after = select_device(get_devices(region, session['at']), config['device_id'])
            report['cloud_online_after'] = bool(after.get('online'))
            report['version_after'] = (after.get('params') or {}).get('fwVersion')
        except Exception as exc:
            report['status_check_error_type'] = type(exc).__name__
    except KeyboardInterrupt:
        report['interrupted'] = True
    except Exception as exc:
        report['error_type'] = type(exc).__name__
    finally:
        credentials.clear()
        if ws:
            ws.close()
        if server:
            server.shutdown()
            server.server_close()
            with server.lock:
                report['capture_records'] = list(server.records)
                report['upstream_attempts'] = server.attempts
        print(json.dumps(report, indent=2))
        write_report(report_path, report)
    return 0 if any(r.get('outcome') == 'verified_file_saved' for r in report.get('capture_records', [])) else 1


if __name__ == '__main__':
    raise SystemExit(main())
