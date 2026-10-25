import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class CliTests(unittest.TestCase):
    def command(self, *args):
        return subprocess.run([sys.executable, '-m', 'folder_report', *map(str, args)],
                              capture_output=True, text=True, encoding='utf-8', check=False)

    def test_help(self):
        result = self.command('--help')
        self.assertEqual(result.returncode, 0)
        self.assertIn('--top', result.stdout)

    def test_empty_unicode_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'каталог'
            root.mkdir()
            result = self.command(root, '--top', '0')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Files: 0', result.stdout)
        self.assertIn('not requested', result.stdout)

    def test_invalid_root_and_top(self):
        for args in [('definitely-missing',), ('.', '--top', '-1'), ('.', '--top', 'bad')]:
            with self.subTest(args=args):
                result = self.command(*args)
                self.assertEqual(result.returncode, 2)
                self.assertNotIn('Traceback', result.stdout + result.stderr)

    def test_duplicates_and_exclusion_flags(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'a.txt').write_bytes(b'hello')
            (root / 'b.txt').write_bytes(b'hello')
            (root / 'ignored.tmp').write_bytes(b'hello')
            result = self.command(root, '--duplicates', '--exclude', '*.tmp')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Duplicate logical bytes: 5', result.stdout)
