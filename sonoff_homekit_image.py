#!/usr/bin/env python3
"""Package the MINIR4 HomeKit prototype offline; cannot send OTA commands."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import zlib
from sonoff_minir4_image import validate, validate_payload


def build(payload,template):
    validate(template);validate_payload(payload)
    if not any(marker in payload for marker in (b'minir4 homekit 0.2.0',b'minir4 homekit 0.2.1',b'minir4 homekit 0.2.2')):
        raise ValueError('Expected the HomeKit prototype, not the readout auxiliary')
    header=bytearray(template[:100])
    header[2:10]=b'9.9.9\0\0\0';header[0x38:0x48]=b'9.9.9'.ljust(16,b'\0')
    struct.pack_into('>I',header,0x4c,len(payload))
    struct.pack_into('>I',header,0x50,zlib.crc32(payload)&0xffffffff)
    struct.pack_into('>I',header,0x54,zlib.crc32(header[0x18:0x54])&0xffffffff)
    struct.pack_into('>I',header,0x14,zlib.crc32(header[:20])&0xffffffff)
    result=bytes(header)+payload;validate(result);return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--payload',type=Path,required=True)
    parser.add_argument('--template',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    data=build(args.payload.read_bytes(),args.template.read_bytes())
    args.output.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as out:out.write(data)
    print(json.dumps({'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),
                      'structure_valid':True,'deployed':False,'homekit_pairing_tested':False},indent=2))


if __name__=='__main__':main()
