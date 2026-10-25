import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


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

    def test_json_success_and_duplicate_reports(self):
        expected_keys = {'schema_version', 'complete', 'duplicates_checked', 'files', 'total_bytes', 'extensions',
                         'largest', 'duplicates', 'duplicate_bytes', 'skipped', 'issues'}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'a.txt').write_bytes(b'hello')
            (root / 'b.txt').write_bytes(b'hello')
            (root / 'данные.txt').write_bytes(b'world')
            for options, checked, total in [((), False, 0), (('--duplicates',), True, 5)]:
                result = self.command(root, '--json', *options)
                self.assertEqual(result.returncode, 0, result.stderr)
                report = json.loads(result.stdout)
                self.assertEqual(set(report), expected_keys)
                self.assertEqual((report['files'], report['total_bytes']), (3, 15))
                self.assertEqual(report['duplicates_checked'], checked)
                self.assertEqual(report['duplicate_bytes'], total)
                self.assertTrue(report['complete'])
                self.assertIn('данные.txt', result.stdout)
                self.assertNotIn(str(root), result.stdout)
                self.assertEqual(result.stderr, '')

    def test_json_invalid_root(self):
        result = self.command('missing-folder', '--json')
        self.assertEqual(result.returncode, 2)
        report = json.loads(result.stdout)
        self.assertFalse(report['complete'])
        self.assertEqual(report['issues'][0]['path'], '.')

    def test_json_partial_scan_and_string_io(self):
        from folder_report.cli import main
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as temp, patch('sys.stdout', output), \
                patch('sys.stderr', io.StringIO()), \
                patch('folder_report.core.os.scandir', side_effect=PermissionError('synthetic denial')):
            code = main([temp, '--json'])
        self.assertEqual(code, 1)
        report = json.loads(output.getvalue())
        self.assertFalse(report['complete'])
        self.assertEqual(report['issues'], [{'path': '.', 'kind': 'permission_denied'}])

    def test_audit_leaves_inputs_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ['a.txt', 'nested/b.txt', '.hidden']:
                file = root / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(b'hello')
            def snapshot():
                return {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns) if path.is_file()
                        else ('directory', path.stat().st_mtime_ns) for path in root.rglob('*')}
            before = snapshot()
            result = self.command(root, '--duplicates', '--json')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(snapshot(), before)
