from pathlib import Path
import os
import tempfile
import unittest

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
