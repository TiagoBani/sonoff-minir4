#!/usr/bin/env python3
"""Capture vendor bytes locally; always return an empty failure to the device.

Accepts a URL pointing at this Mac; forwards its signed path to the vendor.
Does not configure routing, authenticate to eWeLink, or send OTA commands.
"""
import argparse
import hashlib
import http.client
import http.server
import ipaddress
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
import urllib.parse

MAX_BYTES = 16 * 1024 * 1024


def load_manifest(path):
    manifest = json.loads(Path(path).read_text(encoding='utf-8'))
    files = manifest['files']
    if len(files) != 2:
        raise ValueError('Expected exactly two manifest entries')
    entries = {}
    origin = None
    for item in files:
        url = urllib.parse.urlsplit(item['downloadUrl'])
        candidate = (url.scheme, url.hostname, url.port or (443 if url.scheme == 'https' else 80))
        name = item['name']
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password:
            raise ValueError('Invalid vendor origin')
        if not name or Path(name).name != name or name in ('.', '..'):
            raise ValueError('Invalid filename')
        if not re.fullmatch(r'[a-fA-F0-9]{64}', item['digest']):
            raise ValueError('Invalid digest')
        if origin is not None and candidate != origin:
            raise ValueError('Manifest spans more than one origin')
        if url.path in entries:
            raise ValueError('Duplicate manifest path')
        origin = candidate
        entries[url.path] = {'name': name, 'digest': item['digest'].lower()}
    return origin, entries


def fetch_image(origin, path, request_headers=None, timeout=10):
    scheme, host, port = origin
    connection_type = http.client.HTTPSConnection if scheme == 'https' else http.client.HTTPConnection
    connection = connection_type(host, port, timeout=timeout)
    try:
        # Reuse the device's signed path, in memory only. Ask for all bytes.
        headers = {'Connection': 'close', 'Range': f'bytes=0-{MAX_BYTES - 1}'}
        # The MINIR4 uses a different agent from the reference S60. Preserve
        # that protocol field, without persisting or forwarding other headers.
        agent = (request_headers or {}).get('User-Agent')
        if agent:
            headers['User-Agent'] = agent
        connection.request('GET', path, headers=headers)
        response = connection.getresponse()
        if response.status not in (200, 206):
            return response.status, None
        length = response.getheader('Content-Length')
        if length is not None and (int(length) < 1 or int(length) > MAX_BYTES):
            raise ValueError('Invalid content length')
        data = response.read(MAX_BYTES + 1)
        if not data or len(data) > MAX_BYTES:
            raise ValueError('Invalid image size')
        if length is not None and len(data) != int(length):
            raise ValueError('Truncated image')
        if response.status == 206:
            content_range = response.getheader('Content-Range', '')
            match = re.fullmatch(r'bytes 0-(\d+)/(\d+)', content_range)
            if not match or int(match[1]) + 1 != len(data) or int(match[2]) != len(data):
                raise ValueError('Partial image instead of full file')
        return response.status, data
    finally:
        connection.close()


def save_verified(directory, entry, data):
    digest = hashlib.sha256(data).hexdigest()
    if digest != entry['digest']:
        raise ValueError('Digest mismatch')
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    destination = directory / entry['name']
    if destination.exists():
        if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
            raise ValueError('Existing image differs; never overwrite')
        return
    descriptor, temporary = tempfile.mkstemp(dir=directory, prefix='.verified-')
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(data)
        # Linking is exclusive and preserves any concurrent existing file.
        os.link(temporary, destination)
    finally:
        os.unlink(temporary)


class CaptureServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, *, origin, entries, device_id, sources, output,
                 fetcher=fetch_image, max_attempts=4, fetch_siblings=False):
        super().__init__(address, CaptureHandler)
        self.origin = origin
        self.entries = entries
        self.device_id = device_id
        self.sources = set(sources)
        self.output = Path(output)
        self.fetcher = fetcher
        self.max_attempts = max_attempts
        self.attempts = 0
        self.records = []
        self.lock = threading.Lock()
        self.fetch_siblings = fetch_siblings


class CaptureHandler(http.server.BaseHTTPRequestHandler):
    server_version = 'LocalCapture/1.0'
    sys_version = ''
    timeout = 10

    def log_message(self, *args):
        pass  # Never log signed URLs, device IDs, or headers.

    def empty(self, status):
        self.send_response(status)
        self.send_header('Content-Length', '0')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True

    def do_GET(self):
        record = {'accepted': False, 'firmware_bytes_sent_to_device': 0}
        try:
            parsed = urllib.parse.urlsplit(self.path)
            allowed_hosts = {
                f'{self.server.origin[1]}:{self.server.origin[2]}',
                f'{self.server.server_address[0]}:{self.server.server_address[1]}',
            }
            query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            checks = {
                'source': self.client_address[0] in self.server.sources,
                'relative_url': parsed.scheme == '' and parsed.netloc == '',
                'manifest_path': parsed.path in self.server.entries,
                'host': self.headers.get('Host') in allowed_hosts,
                'device_identity': query.get('deviceid') == [self.server.device_id],
                'timestamp_shape': len(query.get('ts', [])) == 1 and query['ts'][0].isdigit(),
                'signature_shape': len(query.get('sign', [])) == 1 and bool(re.fullmatch(r'[a-fA-F0-9]{64}', query['sign'][0])),
                'range': self.headers.get('Range') == 'bytes=0-23',
            }
            if not all(checks.values()):
                record['outcome'] = 'request_rejected'
                record['failed_checks'] = [name for name, valid in checks.items() if not valid]
                return
            with self.server.lock:
                if self.server.attempts >= self.server.max_attempts:
                    record['outcome'] = 'attempt_limit'
                    return
                self.server.attempts += 1
            record['accepted'] = True
            entry = self.server.entries[parsed.path]
            record['file'] = entry['name']
            status, data = self.server.fetcher(
                self.server.origin, self.path, {'User-Agent': self.headers.get('User-Agent')})
            record['upstream_status'] = status
            if data is None:
                record['outcome'] = 'upstream_rejected'
                return
            record['bytes_received_from_vendor'] = len(data)
            with self.server.lock:
                save_verified(self.server.output, entry, data)
            record['outcome'] = 'verified_file_saved'
            if self.server.fetch_siblings:
                related = []
                for sibling_path, sibling in self.server.entries.items():
                    if sibling_path == parsed.path or sibling['digest'] != entry['digest']:
                        continue
                    sibling_record = {'file': sibling['name']}
                    related.append(sibling_record)
                    try:
                        signed_path = urllib.parse.urlunsplit(('', '', sibling_path, parsed.query, ''))
                        sibling_status, sibling_data = self.server.fetcher(
                            self.server.origin, signed_path, {'User-Agent': self.headers.get('User-Agent')})
                        sibling_record['upstream_status'] = sibling_status
                        if sibling_data is None:
                            sibling_record['outcome'] = 'upstream_rejected'
                            continue
                        with self.server.lock:
                            save_verified(self.server.output, sibling, sibling_data)
                        sibling_record.update(outcome='verified_file_saved', bytes_received=len(sibling_data))
                    except Exception as exc:
                        sibling_record.update(outcome='capture_failed', error_type=type(exc).__name__)
                record['related_files'] = related
        except Exception as exc:
            record['outcome'] = 'capture_failed'
            record['error_type'] = type(exc).__name__
        finally:
            with self.server.lock:
                self.server.records.append(record)
            # No success response or firmware body ever goes to the device.
            self.empty(502)

    def do_HEAD(self):
        self.empty(405)

    do_POST = do_HEAD
    do_PUT = do_HEAD
    do_DELETE = do_HEAD
    do_OPTIONS = do_HEAD
    do_PATCH = do_HEAD


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--target', type=Path, required=True)
    parser.add_argument('--listen-ip', required=True)
    parser.add_argument('--port', type=int, default=8088)
    parser.add_argument('--source-ip', action='append', default=[])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=60)
    parser.add_argument('--plan-only', action='store_true',
                        help='save local download URLs without opening a server or sending commands')
    parser.add_argument('--fetch-siblings', action='store_true',
                        help='also request manifest sibling files with identical expected digest')
    args = parser.parse_args()
    local = ipaddress.ip_address(args.listen_ip)
    if not local.is_private or local.is_unspecified or local.is_multicast:
        parser.error('Choose an explicit local interface address')
    if not 1 <= args.seconds <= 300:
        parser.error('Capture window must be between 1 and 300 seconds')
    origin, entries = load_manifest(args.manifest)
    target = json.loads(args.target.read_text(encoding='utf-8'))
    sources = args.source_ip or [target['ip']]
    for source in sources:
        ipaddress.ip_address(source)
    if args.plan_only:
        manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
        local_files = []
        for item in manifest['files']:
            original = urllib.parse.urlsplit(item['downloadUrl'])
            local_url = urllib.parse.urlunsplit(('http', f'{args.listen_ip}:{args.port}',
                                                original.path, original.query, ''))
            local_files.append({'name': item['name'], 'digest': item['digest'],
                                'downloadUrl': local_url})
        plan = {'command_sent': False, 'firmware_bytes_served_to_device': 0,
                'version': manifest['version'], 'binList': local_files,
                'note': 'Plan only; capture server returns empty failure to device.'}
        args.output.mkdir(parents=True, mode=0o700, exist_ok=True)
        with os.fdopen(os.open(args.output / 'local-download-plan.private.json',
                              os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf-8') as output:
            json.dump(plan, output, indent=2)
        print('Plano local preparado; nenhum servidor iniciado ou comando enviado.')
        return
    server = CaptureServer((args.listen_ip, args.port), origin=origin, entries=entries,
                           device_id=target['device_id'], sources=sources, output=args.output,
                           fetch_siblings=args.fetch_siblings)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print('Capturador ativo. Não configura roteador nem envia comandos OTA.')
    try:
        time.sleep(args.seconds)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
    print(json.dumps({'attempts': server.attempts, 'records': server.records,
                      'firmware_bytes_sent_to_device': 0}, indent=2))


if __name__ == '__main__':
    main()
