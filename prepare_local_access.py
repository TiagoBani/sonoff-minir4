#!/usr/bin/env python3
"""Create unique local maintenance credentials offline; never replace existing ones."""
import os
from pathlib import Path
import re
import secrets

ROOT=Path(__file__).resolve().parent


def main():
    path=ROOT/'minir4-readout/main/access.local.h'
    if path.exists():
        data=path.read_text(encoding='utf-8')
        if not re.search(r'^#define READOUT_ACCESS_TOKEN "[0-9a-f]{64}"$',data,re.M):
            raise ValueError('Existing header needs manual review; not overwritten')
        if not re.search(r'^#define READOUT_AP_PASSWORD "[A-Za-z0-9_-]{8,63}"$',data,re.M):
            raise ValueError('Existing AP password needs manual review; not overwritten')
        print('Existing local access credentials preserved.')
        return
    path.parent.mkdir(parents=True,exist_ok=True)
    data=('#pragma once\n#define READOUT_ACCESS_TOKEN "'+secrets.token_hex(32)+'"\n'
          '#define READOUT_AP_PASSWORD "'+secrets.token_urlsafe(24)+'"\n')
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as stream:stream.write(data)
    print('Private local maintenance credentials created; no values printed.')


if __name__=='__main__':main()
