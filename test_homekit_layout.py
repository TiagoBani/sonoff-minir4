"""Check the proposed ranges exclude original firmware, its NVS and bootloader."""
import unittest
from sonoff_homekit_layout import write_allowed, validate


class WriteBoundaryTests(unittest.TestCase):
    def test_storage_only_within_reserve(self):
        self.assertTrue(write_allowed('homekit_storage', 0x19000, 0x4000))
        self.assertFalse(write_allowed('homekit_storage', 0x18FFF, 1))
        self.assertFalse(write_allowed('homekit_storage', 0x1CFFF, 2))
        self.assertFalse(write_allowed('homekit_storage', 0x9000, 0x1000))

    def test_boot_selection_only_in_otadata(self):
        self.assertTrue(write_allowed('boot_selection', 0x1D000, 0x2000))
        self.assertFalse(write_allowed('boot_selection', 0x19000, 0x6000))
        self.assertFalse(write_allowed('boot_selection', 0x1F000, 1))

    def test_only_stock_updater_can_target_homekit_slot(self):
        self.assertTrue(write_allowed('stock_ota', 0x20000, 0x1F0000))
        self.assertFalse(write_allowed('homekit_self_ota', 0x20000, 0x1000))
        self.assertFalse(write_allowed('homekit_storage', 0x20000, 0x1000))

    def test_no_actor_can_write_original_or_bootloader(self):
        for actor in ('homekit_storage', 'boot_selection', 'stock_ota', 'unknown'):
            for start, size in ((0, 0x1000), (0x8000, 0x1000), (0x9000, 1),
                                (0x1F000, 0x1000), (0x210000, 1), (0x20FFFF, 2)):
                self.assertFalse(write_allowed(actor, start, size), (actor, start))

    def test_bad_ranges_and_erase_all_rejected(self):
        for start, size in ((-1, 10), (0x19000, 0), (0x19000, -1),
                            (0, 0x400000), (True, 4096), (0x19000, '4096')):
            self.assertFalse(write_allowed('homekit_storage', start, size))

    def test_truncated_dump_rejected(self):
        with self.assertRaisesRegex(ValueError, '4 MB'):
            validate(bytes(124))


if __name__ == '__main__':
    unittest.main()
