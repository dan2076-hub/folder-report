from pathlib import Path
from contextlib import contextmanager
import os
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from folder_report.core import build_report, scan_directory


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, content):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return target

    def report(self, top=10, exclude=()):
        return build_report(scan_directory(self.root, exclude), top)

    def test_empty_folder(self):
        report = self.report()
        self.assertEqual((report['files'], report['total_bytes'], report['largest']), (0, 0, []))
        self.assertTrue(report['complete'])

    def test_exact_totals(self):
        for name, data in [('a.txt', b'hello'), ('b.txt', b'hello'), ('c.txt', b'world')]:
            self.write(name, data)
        report = self.report()
        self.assertEqual((report['files'], report['total_bytes']), (3, 15))
        self.assertEqual([row['path'] for row in report['largest']], ['a.txt', 'b.txt', 'c.txt'])

    def test_nested_unicode_and_hidden_files(self):
        self.write('nested/данные.TXT', b'123')
        self.write('.hidden', b'12')
        report = self.report()
        self.assertEqual(report['files'], 2)
        self.assertEqual(report['largest'][0]['path'], 'nested/данные.TXT')
        self.assertEqual(report['extensions'][0], {'extension': '.txt', 'files': 1, 'bytes': 3})
        self.assertEqual(report['extensions'][1]['extension'], '(no extension)')

    def test_extension_and_size_order(self):
        self.write('b.ZIP', b'1234')
        self.write('a.txt', b'1234')
        self.write('tiny.TXT', b'1')
        report = self.report(top=1)
        self.assertEqual([row['extension'] for row in report['extensions']], ['.txt', '.zip'])
        self.assertEqual(report['largest'], [{'path': 'a.txt', 'bytes': 4}])
        self.assertEqual(self.report(top=0)['largest'], [])

    def test_default_directory_exclusions(self):
        for directory in ['.git', '.venv', 'venv', 'node_modules', '__pycache__']:
            self.write(directory + '/ignored.txt', b'1234')
        self.write('included.txt', b'x')
        report = self.report()
        self.assertEqual(report['files'], 1)
        self.assertEqual(report['skipped']['excluded'], 5)

    def test_hard_links_count_once(self):
        original = self.write('original.txt', b'hello')
        try:
            os.link(original, self.root / 'alias.txt')
        except OSError as error:
            self.skipTest('Hard links unavailable: ' + type(error).__name__)
        report = self.report()
        self.assertEqual((report['files'], report['total_bytes']), (1, 5))
        self.assertEqual(report['skipped']['hardlinks'], 1)

    def test_missing_and_file_roots(self):
        file = self.write('file.txt', b'x')
        for root in [self.root / 'absent', file]:
            with self.subTest(root=root):
                scan = scan_directory(root, ())
                self.assertTrue(scan.invalid_root)
                self.assertFalse(build_report(scan, 10)['complete'])

    def test_excludes_match_basename_and_relative_path(self):
        self.write('a.tmp', b'x')
        self.write('nested/b.tmp', b'x')
        self.write('cache/inside.txt', b'x')
        self.write('nested/keep.txt', b'x')
        report = self.report(exclude=('*.tmp', 'cache/*'))
        self.assertEqual(report['files'], 1)
        self.assertEqual(report['largest'][0]['path'], 'nested/keep.txt')
        self.assertEqual(report['skipped']['excluded'], 3)

    def test_default_excludes_only_apply_to_directories(self):
        self.write('venv', b'x')
        self.assertEqual(self.report()['files'], 1)

    def test_permission_error_is_partial_and_preserves_other_files(self):
        self.write('private/file', b'x')
        self.write('visible', b'hello')
        original = os.scandir
        def restricted(path):
            if Path(path).name == 'private':
                raise PermissionError('synthetic denial')
            return original(path)
        with patch('folder_report.core.os.scandir', side_effect=restricted):
            report = self.report()
        self.assertFalse(report['complete'])
        self.assertEqual(report['files'], 1)
        self.assertEqual(report['issues'], [{'path': 'private', 'kind': 'permission_denied'}])

    def test_enumeration_order_does_not_change_report(self):
        for name in ['z/a.txt', 'a.txt', 'b.TXT', 'another/deep/c']:
            self.write(name, b'hello')
        expected = self.report()
        original = os.scandir
        @contextmanager
        def reversed_scandir(path):
            with original(path) as iterator:
                entries = list(iterator)
            yield iter(reversed(entries))
        with patch('folder_report.core.os.scandir', side_effect=reversed_scandir):
            self.assertEqual(self.report(), expected)

    def test_reparse_directory_metadata_prevents_recursion(self):
        self.write('junction/never-read.txt', b'outside')
        original = Path.lstat
        flag = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
        def reparse(path):
            if path == self.root / 'junction':
                return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=flag)
            return original(path)
        with patch.object(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', flag, create=True), \
                patch('pathlib.Path.lstat', reparse):
            report = self.report()
        self.assertEqual(report['files'], 0)
        self.assertEqual(report['skipped']['links'], 1)
        self.assertTrue(report['complete'])

    def test_real_symlinks_and_cycles_are_skipped(self):
        self.write('actual.txt', b'hello')
        try:
            os.symlink(self.root, self.root / 'cycle', target_is_directory=True)
            os.symlink(self.root / 'actual.txt', self.root / 'alias.txt')
        except OSError as error:
            self.skipTest('Symlink creation unavailable: ' + type(error).__name__)
        report = self.report()
        self.assertEqual(report['files'], 1)
        self.assertEqual(report['skipped']['links'], 2)

    def test_missing_file_metadata_becomes_an_issue(self):
        self.write('vanished', b'hello')
        original = Path.lstat
        def disappeared(path):
            if path.name == 'vanished':
                raise FileNotFoundError('synthetic disappearance')
            return original(path)
        with patch('pathlib.Path.lstat', disappeared):
            report = self.report()
        self.assertFalse(report['complete'])
        self.assertEqual(report['issues'], [{'path': 'vanished', 'kind': 'unreadable'}])
