#!/usr/bin/env python3
"""Read one owner's Sonoff announcements; never control or update a module."""
import argparse
import getpass
import json
import os
from pathlib import Path
import sys


ENV_KEYS = ('EWELINK_EMAIL', 'EWELINK_PASSWORD', 'EWELINK_REGION', 'EWELINK_COUNTRY_CODE')


def load_credentials(path, environ=None):
    """Read literal values; never evaluate shell substitutions or interpolate."""
    values = {}
    if path.exists():
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            key, separator, value = line.partition('=')
            key, value = key.strip(), value.strip()
            if not separator or key not in ENV_KEYS:
                raise ValueError(f'Formato inválido no arquivo de ambiente, linha {number}.')
            if value[:1] in ('"', "'"):
                if len(value) < 2 or value[-1] != value[0]:
                    raise ValueError(f'Aspas incompletas no arquivo de ambiente, linha {number}.')
                value = value[1:-1]
            values[key] = value
    environment = os.environ if environ is None else environ
    for key in ENV_KEYS:
        if key in environment:
            values[key] = environment[key]
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--discover-only', action='store_true')
    parser.add_argument('--check-env', action='store_true', help='validate credentials without network access')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    credentials = {}
    if not args.discover_only:
        try:
            credentials = load_credentials(root / '.env')
        except (ValueError, OSError):
            print('Não foi possível carregar o arquivo de ambiente. Confira o formato e as permissões.')
            return 1
    if args.check_env:
        complete = bool(credentials.get('EWELINK_EMAIL') and credentials.get('EWELINK_PASSWORD'))
        valid_region = credentials.get('EWELINK_REGION', 'us') in ('us', 'eu', 'as', 'cn')
        print('Credenciais preenchidas:', complete)
        print('Região válida:', valid_region)
        print('Nenhuma conexão de rede realizada; nenhum valor secreto exibido.')
        return 0 if complete and valid_region else 1
    config = json.loads((root / 'target.local.json').read_text(encoding='utf-8'))
    sys.path.insert(0, str(root / 'firmware-liberator'))
    from tools.ewelink.discover_ewelink import discover
    from tools.autoflash.ewelink_lan import advert_fields, advert_state

    report = discover(timeout=8, target=config['ip'])
    fields = advert_fields(report, config['device_id'])
    if not fields:
        print('O módulo esperado não respondeu à descoberta. Nenhuma alteração enviada.')
        return 1
    print('Módulo esperado encontrado. Estado criptografado:', fields.get('encrypt') == 'true')
    if args.discover_only:
        return 0

    from tools.ewelink.get_device_key import login, get_devices, select_device
    email = credentials.get('EWELINK_EMAIL') or input('E-mail eWeLink (somente neste terminal): ').strip()
    password = credentials.get('EWELINK_PASSWORD') or getpass.getpass('Senha eWeLink (oculta): ')
    region = credentials.get('EWELINK_REGION') or 'us'
    country = credentials.get('EWELINK_COUNTRY_CODE') or '+55'
    credentials.clear()
    if region not in ('us', 'eu', 'as', 'cn'):
        print('Região inválida. Nenhuma alteração enviada.')
        return 1
    try:
        region, token = login(email, password, country, region)
        password = ''
        device = select_device(get_devices(region, token), config['device_id'])
        token = ''
        # Refresh the advertisement after the interactive login.
        fields = advert_fields(discover(timeout=8, target=config['ip']), config['device_id'])
        state = advert_state(fields, device['devicekey']) if fields else None
        device = None
        if state is None:
            print('Conta autenticada, mas não foi possível decifrar um anúncio do módulo.')
            return 1
        allowed = ('fwVersion', 'rssi', 'switch', 'switches', 'startup', 'relaySeparation')
        print('Leitura local decifrada com sucesso:')
        print(json.dumps({k: state[k] for k in allowed if k in state}, ensure_ascii=False, indent=2))
        print('Nenhum comando de controle, download ou atualização foi enviado.')
        return 0
    except Exception as exc:
        # Do not echo API response bodies or credentials into a log.
        print('Não foi possível concluir a leitura autenticada. Tipo:', type(exc).__name__)
        return 1
    finally:
        password = ''


if __name__ == '__main__':
    raise SystemExit(main())
