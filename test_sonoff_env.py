import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('probe', Path(__file__).with_name('sonoff_read_only.py'))
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class EnvironmentTests(unittest.TestCase):
    def load(self, content, environ=None):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            path.write_text(content, encoding='utf-8')
            return probe.load_credentials(path, environ or {})

    def test_password_is_literal(self):
        value = 'example#with=$HOME$(echo nope)\\path'
        result = self.load("EWELINK_PASSWORD='" + value + "'\n")
        self.assertEqual(result['EWELINK_PASSWORD'], value)

    def test_environment_overrides_file(self):
        result = self.load('EWELINK_REGION=eu\n', {'EWELINK_REGION': 'us'})
        self.assertEqual(result['EWELINK_REGION'], 'us')

    def test_bad_line_does_not_echo_secret(self):
        with self.assertRaises(ValueError) as caught:
            self.load('EWELINK_PASSWORD="private-example\n')
        self.assertNotIn('private-example', str(caught.exception))

    def test_comments_and_empty_credentials(self):
        result = self.load('# comment\n\nEWELINK_PASSWORD=\n')
        self.assertEqual(result['EWELINK_PASSWORD'], '')


if __name__ == '__main__':
    unittest.main()
