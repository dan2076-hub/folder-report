"""Chunked hashing followed by byte comparison with metadata checks."""
from collections import defaultdict
from contextlib import contextmanager
import errno
import hashlib
import os
import stat

from .core import FileRecord, is_link_or_reparse

CHUNK_SIZE = 1024 * 1024


class FileReadError(Exception):
    def __init__(self, path: str, kind: str):
        super().__init__(kind)
        self.path = path
        self.kind = kind


def read_error(record: FileRecord, error: OSError) -> FileReadError:
    if isinstance(error, PermissionError):
        kind = 'permission_denied'
    elif error.errno in {errno.ENOENT, errno.ENOTDIR, errno.ELOOP, getattr(errno, 'ESTALE', -1)}:
        kind = 'changed'
    else:
        kind = 'unreadable'
    return FileReadError(record.path, kind)


def validate_metadata(record: FileRecord, metadata) -> None:
    fingerprint = metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns
    if is_link_or_reparse(metadata) or not stat.S_ISREG(metadata.st_mode) or fingerprint != record.fingerprint:
        raise FileReadError(record.path, 'changed')


def check_path(record: FileRecord) -> None:
    try:
        validate_metadata(record, record.absolute_path.lstat())
    except OSError as error:
        raise read_error(record, error) from None


@contextmanager
def checked_stream(record: FileRecord):
    check_path(record)
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    try:
        descriptor = os.open(record.absolute_path, flags)
        with os.fdopen(descriptor, 'rb') as stream:
            validate_metadata(record, os.fstat(stream.fileno()))
            yield stream
            validate_metadata(record, os.fstat(stream.fileno()))
            check_path(record)
    except OSError as error:
        raise read_error(record, error) from None


def digest_stream(stream) -> str:
    digest = hashlib.sha256()
    while True:
        chunk = stream.read(CHUNK_SIZE)
        if not chunk:
            return digest.hexdigest()
        digest.update(chunk)


def stable_digest(record: FileRecord) -> str:
    with checked_stream(record) as stream:
        return digest_stream(stream)


def same_bytes(left: FileRecord, right: FileRecord) -> bool:
    with checked_stream(left) as first, checked_stream(right) as second:
        while True:
            left_chunk = first.read(CHUNK_SIZE)
            right_chunk = second.read(CHUNK_SIZE)
            if left_chunk != right_chunk:
                return False
            if not left_chunk:
                return True


def find_duplicates(records: list[FileRecord]) -> tuple[list[dict], list[dict]]:
    sizes = defaultdict(list)
    for record in sorted(records, key=lambda item: item.path):
        sizes[record.size].append(record)
    issues: dict[str, str] = {}
    duplicates = []
    for size in sorted(sizes):
        if len(sizes[size]) < 2:
            continue
        hashes = defaultdict(list)
        for record in sizes[size]:
            try:
                hashes[stable_digest(record)].append(record)
            except FileReadError as error:
                issues[error.path] = error.kind
        for hashed_records in hashes.values():
            if len(hashed_records) < 2:
                continue
            # A hash collision may contain several distinct byte sequences.
            equivalent_groups: list[list[FileRecord]] = []
            for record in hashed_records:
                placed = False
                for group in equivalent_groups:
                    while record.path not in issues:
                        representative = next((item for item in group if item.path not in issues), None)
                        if representative is None:
                            break
                        try:
                            equal = same_bytes(representative, record)
                        except FileReadError as error:
                            issues[error.path] = error.kind
                            continue
                        if equal:
                            group.append(record)
                            placed = True
                        break
                    if placed or record.path in issues:
                        break
                if not placed and record.path not in issues:
                    equivalent_groups.append([record])
            for group in equivalent_groups:
                valid = []
                for record in group:
                    if record.path in issues:
                        continue
                    try:
                        check_path(record)
                        valid.append(record.path)
                    except FileReadError as error:
                        issues[error.path] = error.kind
                if len(valid) > 1:
                    duplicates.append({'bytes_each': size, 'paths': sorted(valid), 'duplicate_bytes': (len(valid) - 1) * size})
    duplicates.sort(key=lambda group: (-group['duplicate_bytes'], group['paths'][0]))
    return duplicates, [{'path': path, 'kind': kind} for path, kind in sorted(issues.items())]
