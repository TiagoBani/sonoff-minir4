"""Check prototype packaging and authenticated maintenance without a real module."""
import hashlib
import json
import unittest
import test_minir4_image as image_fixture
from sonoff_homekit_image import build
from sonoff_homekit_ctl import HomeKitReader
from sonoff_minir4_image import validate
from sonoff_minir4_install import check_purpose


def homekit_payload():
    data=bytearray(image_fixture.payload())
    old=b'minir4 readout 0.1.0';new=b'minir4 homekit 0.2.0'
    assert len(old)==len(new)
    position=data.index(old);data[position:position+len(old)]=new
    # This fixture has one segment; rebuild checksum/hash after changing the marker.
    segment_size=int.from_bytes(data[28:32],'little');checksum=0xEF
    for value in data[32:32+segment_size]:checksum^=value
    data[-33]=checksum;data[-32:]=hashlib.sha256(data[:-32]).digest()
    return bytes(data)


class FakeClient(HomeKitReader):
    def __init__(self):
        super().__init__('127.0.0.1','test-only-token','12:34:56:ab:cd:ef',port=8080)
        self.calls=[]
        self.state={'app':'minir4 homekit 0.2.0','mac':self.mac,'paired_controllers':1,
                    'homekit_on_seen':True,'homekit_off_seen':True,'storage_failed':False}
    def request(self,path,method='GET',limit=4096):
        self.calls.append((method,path))
        return (json.dumps(self.state).encode(),None) if path=='/status' else (b'Accepted',None)


class HomeKitToolTests(unittest.TestCase):
    def test_installer_requires_explicit_homekit_purpose(self):
        data=build(homekit_payload(),image_fixture.template())
        check_purpose(data,True)
        with self.assertRaisesRegex(ValueError,'purpose'):
            check_purpose(data,False)
        with self.assertRaisesRegex(ValueError,'purpose'):
            check_purpose(image_fixture.payload(),True)

    def test_homekit_package_has_valid_wrapper_and_payload(self):
        report=validate(build(homekit_payload(),image_fixture.template()))
        self.assertEqual(report['wrapper']['header_version'],'9.9.9')
        self.assertFalse(report['deployment_validated'])

    def test_readout_not_accepted_as_homekit(self):
        with self.assertRaisesRegex(ValueError,'prototype'):
            build(image_fixture.payload(),image_fixture.template())

    def test_c3_rejected(self):
        bad=bytearray(homekit_payload());bad[12]=5
        with self.assertRaisesRegex(ValueError,'classic ESP32'):
            build(bad,image_fixture.template())

    def test_status_does_not_write(self):
        reader=FakeClient();reader.action('status')
        self.assertEqual(reader.calls,[('GET','/status')])

    def test_wrong_device_never_receives_return(self):
        reader=FakeClient();reader.state['mac']='12:34:56:00:00:00'
        with self.assertRaisesRegex(ValueError,'identity'):
            reader.action('return')
        self.assertEqual(reader.calls,[('GET','/status')])

    def test_unproven_or_failed_trial_cannot_be_promoted(self):
        for field,value in [('paired_controllers',0),('homekit_on_seen',False),
                            ('homekit_off_seen',False),('storage_failed',True),('homekit_ready',False),('startup_failed',True)]:
            reader=FakeClient();reader.state[field]=value
            with self.assertRaisesRegex(ValueError,'test on/off'):
                reader.action('commit')
            self.assertEqual(reader.calls,[('GET','/status')])

    def test_return_and_commit_are_explicit_and_identity_checked(self):
        for action in ('return','commit'):
            reader=FakeClient();result=reader.action(action)
            self.assertEqual(reader.calls,[('GET','/status'),('POST','/'+action)])
            self.assertTrue(result['physical_outcome_needs_confirmation'])


if __name__=='__main__':unittest.main()
