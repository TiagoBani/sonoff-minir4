#!/usr/bin/env python3
"""Create private HomeKit setup material offline, without logging its values."""
import ast
import hashlib
import json
import os
from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parent


def group():
    # Read the pinned SDK's standard HomeKit SRP group without executing its tool.
    source = ROOT / 'esp-homekit-reference/tools/mfg_homekit/hk_mfg_gen.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'n_3072' for t in node.targets):
            value = int(ast.literal_eval(node.value), 16)
            if value.bit_length() == 3072:
                return value
    raise ValueError('Expected the SDK HomeKit SRP group')


def verifier(pin, salt):
    if len(salt) != 16:
        raise ValueError('Expected a 16-byte salt')
    identity = hashlib.sha512(('Pair-Setup:' + pin).encode()).digest()
    exponent = int.from_bytes(hashlib.sha512(salt + identity).digest(), 'big')
    return pow(5, exponent, group()).to_bytes(384, 'big')


def main():
    output = ROOT / 'homekit-plan/pairing.local.json'
    header = ROOT / 'minir4-homekit/main/pairing.local.h'
    if output.exists():
        data = json.loads(output.read_text(encoding='utf-8'))
    else:
        invalid = {'00000000','11111111','22222222','33333333','44444444','55555555',
                   '66666666','77777777','88888888','99999999','12345678','87654321'}
        while True:
            raw = ''.join(str(secrets.randbelow(10)) for _ in range(8))
            if raw not in invalid:
                break
        data = {'setup_code': raw[:3] + '-' + raw[3:5] + '-' + raw[5:],
                'setup_id': ''.join(secrets.choice('0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ') for _ in range(4)),
                'salt': secrets.token_hex(16)}
        fd = os.open(output, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as out:
            json.dump(data, out, indent=2)
    salt = bytes.fromhex(data['salt'])
    key = verifier(data['setup_code'], salt)
    def array(value):
        return ','.join('0x%02x' % b for b in value)
    content = ('#pragma once\n#define HK_SETUP_ID "' + data['setup_id'] + '"\n' +
               'static const hap_setup_info_t HK_SETUP_INFO = { .salt={' + array(salt) +
               '}, .verifier={' + array(key) + '} };\n')
    if header.exists() and header.read_text() != content:
        raise ValueError('Existing pairing header differs; preserve it for review')
    if not header.exists():
        fd = os.open(header, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as out:
            out.write(content)
    assert data['setup_code'] not in content
    assert data['setup_code'].replace('-', '') not in content
    print('Private pairing material ready; only salt/verifier and setup ID enter the firmware.')


if __name__ == '__main__':
    main()
