#!/usr/bin/env python3
"""Send only the encrypted getState query; never send update/control commands."""
import json
from pathlib import Path
import sys


def main():
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    from sonoff_read_only import load_credentials
    sys.path.insert(0, str(root / 'firmware-liberator'))
    from tools.ewelink.get_device_key import login, get_devices, select_device
    from archive.tools.lan_get_state import get_state
    credentials = load_credentials(root / '.env')
    config = json.loads((root / 'target.local.json').read_text(encoding='utf-8'))
    try:
        region, token = login(credentials['EWELINK_EMAIL'], credentials['EWELINK_PASSWORD'],
                              credentials.get('EWELINK_COUNTRY_CODE') or '+55',
                              credentials.get('EWELINK_REGION') or 'us')
        credentials.clear()
        device = select_device(get_devices(region, token), config['device_id'])
        token = ''
        result = get_state(config['ip'], 8081, device, timeout=5)
        device = None
        reply = result.get('reply')
        summary = {
            'http_status': result.get('http_status'),
            'json_response': isinstance(reply, dict),
            'device_error': reply.get('error') if isinstance(reply, dict) else None,
            'encrypted_reply_decoded': 'decrypted' in result,
        }
        print(json.dumps(summary, indent=2))
        print('Somente getState enviado; sem controle, desbloqueio, download ou atualização.')
        return 0 if summary['http_status'] == 200 else 1
    except Exception as exc:
        print('Consulta não concluída. Tipo:', type(exc).__name__)
        return 1
    finally:
        credentials.clear()


if __name__ == '__main__':
    raise SystemExit(main())
