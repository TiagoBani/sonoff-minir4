"""Exercise the real C storage backend with a fault-injecting IDF substitute."""
import ctypes as c
import os
import sys
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import zlib

ROOT=Path(__file__).resolve().parent


def owned_partition():
    data=bytearray(b'\xff'*0x4000)
    page=bytearray(b'\xff'*4096)
    struct.pack_into('<II',page,0,0xFFFFFFFE,0);page[8]=0xFE
    struct.pack_into('<I',page,28,zlib.crc32(page[4:28],0xFFFFFFFF))
    def entry(index,ns,kind,span,key,value):
        e=bytearray(struct.pack('<BBBBI16s8s',ns,kind,span,0xFF,0,key.encode().ljust(16,b'\0'),value))
        struct.pack_into('<I',e,4,zlib.crc32(e[:4]+e[8:],0xFFFFFFFF))
        page[64+index*32:96+index*32]=e
        for i in range(index,index+span):page[32+i//4]&=~(1<<((i%4)*2))
    owner=b'minir4-hk-v1\0'
    entry(0,0,1,1,'minir4_ctl',b'\x01'+b'\xff'*7)
    entry(1,1,0x21,2,'owner',struct.pack('<H2sI',len(owner),b'\xff\xff',zlib.crc32(owner,0xFFFFFFFF)))
    page[128:128+len(owner)]=owner;data[:4096]=page
    return data


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        path=Path(self.temp.name)/'storage.dylib'
        src=ROOT/'minir4-homekit/main'
        subprocess.run(['clang',('-dynamiclib' if sys.platform=='darwin' else '-shared'),'-fPIC','-Wall','-Wextra','-Werror','-I'+str(ROOT/'tests_homekit/include'),
            '-I'+str(src),str(src/'store.c'),str(src/'store_policy.c'),str(src/'lifecycle.c'),
            str(ROOT/'minir4-homekit/components/esp_hap_platform/keystore.c'),
            str(ROOT/'tests_homekit/mock_idf.c'),'-o',str(path)],check=True)
        self.lib=c.CDLL(str(path));self.raw=(c.c_uint8*0x4000).in_dll(self.lib,'mock_flash')
        self.raw[:]=b'\xff'*0x4000
        self.lib.hk_storage_init.restype=c.c_bool
        self.lib.hk_storage_failed.restype=c.c_bool
        self.lib.hk_storage_classify.argtypes=[c.c_void_p,c.c_size_t]
        self.lib.hk_set_commit.argtypes=[c.c_void_p];self.lib.hk_set_commit.restype=c.c_bool
        self.lib.hk_committed.argtypes=[c.c_void_p];self.lib.hk_committed.restype=c.c_bool
        self.lib.hk_clear_commit.restype=c.c_bool
        self.lib.hk_can_commit.argtypes=[c.c_bool]*4;self.lib.hk_can_commit.restype=c.c_bool
        self.lib.hk_trial_expired.argtypes=[c.c_bool,c.c_uint32];self.lib.hk_trial_expired.restype=c.c_bool

    def tearDown(self):self.temp.cleanup()
    def flag(self,name):return c.c_int.in_dll(self.lib,'mock_'+name)

    def test_boot_diagnostic_is_bounded_and_failures_block_promotion(self):
        self.lib.hk_boot_stage_write.restype=c.c_bool
        self.lib.hk_boot_stage_read.restype=c.c_uint8
        self.assertFalse(self.lib.hk_boot_stage_write(1))
        self.assertTrue(self.lib.hk_storage_init())
        self.assertEqual(self.lib.hk_boot_stage_read(),0)
        self.assertTrue(self.lib.hk_boot_stage_write(4))
        self.assertEqual(self.lib.hk_boot_stage_read(),4)
        self.assertFalse(self.lib.hk_boot_stage_write(9))
        self.flag('commit_error').value=-99
        self.assertFalse(self.lib.hk_boot_stage_write(5))
        self.assertTrue(self.lib.hk_storage_failed())

    def test_unknown_data_rejected_before_nvs_initialization(self):
        self.raw[100]=0
        self.assertFalse(self.lib.hk_storage_init())
        self.assertEqual(self.flag('init_calls').value,0)
        self.assertEqual(self.flag('write_calls').value,0)

    def test_full_nvs_refused_without_erase(self):
        self.flag('init_error').value=-99
        self.assertFalse(self.lib.hk_storage_init())
        self.assertEqual(self.flag('erase_calls').value,0)

    def test_partition_address_mismatch_refused(self):
        (c.c_uint32*2).in_dll(self.lib,'mock_partition')[0]=0x9000
        self.assertFalse(self.lib.hk_storage_init())
        self.assertEqual(self.flag('init_calls').value,0)

    def test_known_owner_accepted_and_corruption_rejected(self):
        owned=owned_partition();self.raw[:]=owned
        self.assertEqual(self.lib.hk_storage_classify(self.raw,len(self.raw)),2)
        self.raw[128]^=1
        self.assertEqual(self.lib.hk_storage_classify(self.raw,len(self.raw)),0)
        self.raw[:]=owned;self.raw[8192+55]=0
        self.assertEqual(self.lib.hk_storage_classify(self.raw,len(self.raw)),0)

    def test_owner_generated_by_official_idf_tool_is_accepted(self):
        directory=Path(self.temp.name)
        source=directory/'owner.csv';image=directory/'reserve.bin'
        source.write_text('key,type,encoding,value\nminir4_ctl,namespace,,\nowner,data,string,minir4-hk-v1\n')
        python=os.environ.get('SONOFF_NVS_PYTHON',sys.executable)
        subprocess.run([str(python),'-m','esp_idf_nvs_partition_gen','generate',str(source),str(image),'0x4000'],
                       check=True,stdout=subprocess.DEVNULL)
        self.raw[:]=image.read_bytes()
        self.assertEqual(self.lib.hk_storage_classify(self.raw,len(self.raw)),2)

    def test_sdk_cannot_touch_sonoff_or_control_namespace(self):
        self.assertTrue(self.lib.hk_storage_init())
        before=self.flag('open_calls').value
        for part,ns in [(b'nvs',b'hap_main'),(b'reserve',b'pair'),(b'reserve',b'minir4_ctl'),(b'reserve',b'hap_setup')]:
            self.assertEqual(self.lib.hap_platform_keystore_set(part,ns,b'x',b'x',1),-1)
        self.assertEqual(self.flag('open_calls').value,before)
        self.assertEqual(self.lib.hap_platfrom_keystore_erase_partition(b'reserve'),-1)
        self.assertEqual(self.flag('erase_calls').value,0)

    def test_write_failure_is_sticky_and_blocks_promotion(self):
        self.assertTrue(self.lib.hk_storage_init());self.flag('set_error').value=-99
        self.assertEqual(self.lib.hap_platform_keystore_set(b'reserve',b'hap_ctrl',b'1',b'x',1),-1)
        self.assertTrue(self.lib.hk_storage_failed())
        self.assertFalse(self.lib.hk_set_commit(c.create_string_buffer(bytes(32))))

    def test_commit_failure_propagates(self):
        self.assertTrue(self.lib.hk_storage_init());self.flag('commit_error').value=-99
        self.assertFalse(self.lib.hk_set_commit(c.create_string_buffer(bytes(32))))
        self.assertTrue(self.lib.hk_storage_failed())

    def test_failed_storage_still_allows_clearing_promotion(self):
        self.assertTrue(self.lib.hk_storage_init())
        digest=c.create_string_buffer(b'1'*32)
        self.assertTrue(self.lib.hk_set_commit(digest))
        self.flag('set_error').value=-99
        self.lib.hap_platform_keystore_set(b'reserve',b'hap_ctrl',b'1',b'x',1)
        self.assertTrue(self.lib.hk_storage_failed())
        self.assertTrue(self.lib.hk_clear_commit())
        self.assertFalse(self.lib.hk_committed(digest))

    def test_promotion_bound_to_exact_image_and_cleared_on_return(self):
        self.assertTrue(self.lib.hk_storage_init())
        one=c.create_string_buffer(b'1'*32);two=c.create_string_buffer(b'2'*32)
        self.assertTrue(self.lib.hk_set_commit(one));self.assertTrue(self.lib.hk_committed(one))
        self.assertFalse(self.lib.hk_committed(two));self.assertTrue(self.lib.hk_clear_commit())
        self.assertFalse(self.lib.hk_committed(one))

    def test_trial_expires_but_committed_does_not(self):
        self.assertFalse(self.lib.hk_trial_expired(False,1199999))
        self.assertTrue(self.lib.hk_trial_expired(False,1200000))
        self.assertFalse(self.lib.hk_trial_expired(True,4000000))
        self.assertTrue(self.lib.hk_can_commit(True,True,True,False))
        for flags in [(False,True,True,False),(True,False,True,False),(True,True,False,False),(True,True,True,True)]:
            self.assertFalse(self.lib.hk_can_commit(*flags))


if __name__=='__main__':unittest.main()
