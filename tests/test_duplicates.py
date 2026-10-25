import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from folder_report.core import scan_directory
from folder_report.duplicates import FileReadError, find_duplicates, same_bytes, stable_digest


class DuplicateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def records(self):
        return scan_directory(self.root, ()).records

    def test_hello_hello_world(self):
        for name, data in [('a.txt', b'hello'), ('b.txt', b'hello'), ('c.txt', b'world')]:
            self.write(name, data)
        groups, issues = find_duplicates(self.records())
        self.assertEqual(groups, [{'bytes_each': 5, 'paths': ['a.txt', 'b.txt'], 'duplicate_bytes': 5}])
        self.assertEqual(issues, [])

    def test_hash_collisions_are_split_by_actual_bytes(self):
        for name, data in [('a', b'hello'), ('b', b'world'), ('c', b'hello'), ('d', b'world')]:
            self.write(name, data)
        with patch('folder_report.duplicates.stable_digest', return_value='mocked-collision'):
            groups, issues = find_duplicates(self.records())
        self.assertEqual([group['paths'] for group in groups], [['a', 'c'], ['b', 'd']])
        self.assertEqual(issues, [])

    def test_unique_sizes_are_not_hashed(self):
        self.write('a', b'x')
        self.write('b', b'yy')
        with patch('folder_report.duplicates.stable_digest') as digest:
            self.assertEqual(find_duplicates(self.records()), ([], []))
        digest.assert_not_called()

    def test_nested_and_empty_duplicates(self):
        for name in ['z', 'nested/a', 'empty']:
            self.write(name, b'')
        groups, issues = find_duplicates(self.records())
        self.assertEqual(groups, [{'bytes_each': 0, 'paths': ['empty', 'nested/a', 'z'], 'duplicate_bytes': 0}])
        self.assertEqual(issues, [])

    def test_large_files_use_complete_contents(self):
        data = b'x' * (1024 * 1024 + 123)
        self.write('a', data)
        self.write('b', data)
        records = self.records()
        self.assertEqual(stable_digest(records[0]), hashlib.sha256(data).hexdigest())
        self.assertTrue(same_bytes(*records))

    def test_changed_after_scan_is_not_a_duplicate(self):
        first = self.write('a', b'hello')
        self.write('b', b'hello')
        records = self.records()
        first.write_bytes(b'world')
        os.utime(first, ns=(records[0].mtime_ns, records[0].mtime_ns + 1000000))
        groups, issues = find_duplicates(records)
        self.assertEqual(groups, [])
        self.assertEqual(issues, [{'path': 'a', 'kind': 'changed'}])

    def test_changed_during_hash_is_detected(self):
        from folder_report import duplicates
        first = self.write('a', b'hello')
        record = self.records()[0]
        original_digest = duplicates.digest_stream
        def change_during_read(stream):
            digest = original_digest(stream)
            os.utime(first, ns=(record.mtime_ns, record.mtime_ns + 1000000))
            return digest
        with patch('folder_report.duplicates.digest_stream', side_effect=change_during_read):
            with self.assertRaises(FileReadError) as caught:
                stable_digest(record)
        self.assertEqual(caught.exception.kind, 'changed')

    def test_disappeared_file_is_a_changed_issue(self):
        first = self.write('a', b'hello')
        self.write('b', b'hello')
        records = self.records()
        first.unlink()
        groups, issues = find_duplicates(records)
        self.assertEqual(groups, [])
        self.assertEqual(issues, [{'path': 'a', 'kind': 'changed'}])

    def test_hard_link_alias_does_not_inflate_duplicate_bytes(self):
        first = self.write('a', b'hello')
        self.write('b', b'hello')
        try:
            os.link(first, self.root / 'alias')
        except OSError as error:
            self.skipTest('Hard links unavailable: ' + type(error).__name__)
        scan = scan_directory(self.root, ())
        groups, issues = find_duplicates(scan.records)
        self.assertEqual(scan.skipped['hardlinks'], 1)
        self.assertEqual(sum(group['duplicate_bytes'] for group in groups), 5)
        self.assertEqual(issues, [])

    def test_unreadable_content_is_an_issue(self):
        self.write('a', b'hello')
        self.write('b', b'hello')
        with patch('folder_report.duplicates.os.open', side_effect=PermissionError('synthetic denial')):
            groups, issues = find_duplicates(self.records())
        self.assertEqual(groups, [])
        self.assertEqual(issues, [{'path': 'a', 'kind': 'permission_denied'}, {'path': 'b', 'kind': 'permission_denied'}])

    def test_changed_representative_does_not_hide_other_duplicates(self):
        from folder_report import duplicates
        first = self.write('a', b'hello')
        self.write('b', b'hello')
        self.write('c', b'hello')
        records = self.records()
        original = duplicates.same_bytes
        changed = False
        def replace_representative(left, right):
            nonlocal changed
            if not changed:
                changed = True
                first.write_bytes(b'world')
                os.utime(first, ns=(records[0].mtime_ns, records[0].mtime_ns + 1000000))
            return original(left, right)
        with patch('folder_report.duplicates.same_bytes', side_effect=replace_representative):
            groups, issues = find_duplicates(records)
        self.assertEqual(groups, [{'bytes_each': 5, 'paths': ['b', 'c'], 'duplicate_bytes': 5}])
        self.assertEqual(issues, [{'path': 'a', 'kind': 'changed'}])

    def test_final_path_check_rejects_changes_after_comparison(self):
        from folder_report import duplicates
        first = self.write('a', b'hello')
        self.write('b', b'hello')
        records = self.records()
        original = duplicates.same_bytes
        def change_after_compare(left, right):
            equal = original(left, right)
            os.utime(first, ns=(records[0].mtime_ns, records[0].mtime_ns + 1000000))
            return equal
        with patch('folder_report.duplicates.same_bytes', side_effect=change_after_compare):
            groups, issues = find_duplicates(records)
        self.assertEqual(groups, [])
        self.assertEqual(issues, [{'path': 'a', 'kind': 'changed'}])
