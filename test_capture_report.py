from pathlib import Path
import stat
import tempfile
import unittest

from sonoff_capture_probe import write_report


class ReportTests(unittest.TestCase):
    def test_creates_missing_report_directory_privately(self):
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / 'new-run-directory' / 'run.json'
            write_report(report, {'command_sent': False})
            self.assertTrue(report.exists())
            self.assertEqual(stat.S_IMODE(report.stat().st_mode), 0o600)

    def test_does_not_overwrite_an_existing_run(self):
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / 'run.json'
            write_report(report, {'command_sent': False})
            original = report.read_bytes()
            with self.assertRaises(FileExistsError):
                write_report(report, {'command_sent': True})
            self.assertEqual(report.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
