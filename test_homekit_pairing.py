"""Compare the setup verifier against Espressif's own SRP tool, using a fake PIN."""
import importlib.util
from pathlib import Path
import sys
import unittest
from prepare_homekit_pairing import verifier, group

ROOT=Path(__file__).resolve().parent


class PairingTests(unittest.TestCase):
    def test_matches_sdk_srp_with_fixed_salt(self):
        path=ROOT/'esp-homekit-reference/tools/srp/srp_tool.py'
        spec=importlib.util.spec_from_file_location('sdk_srp',path)
        srp=importlib.util.module_from_spec(spec);spec.loader.exec_module(srp)
        pin='111-22-333';salt=bytes(range(16))
        _,expected=srp.create_salted_verification_key('Pair-Setup',pin,srp.SHA512,srp.NG_CUSTOM,
                    format(group(),'X').encode(),b'5',salt=salt.hex())
        self.assertEqual(verifier(pin,salt),expected.rjust(384,b'\0'))


if __name__=='__main__':unittest.main()
