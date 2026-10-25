"""Read-only traversal and deterministic logical-size summaries."""
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
import os
from pathlib import Path
import stat

DEFAULT_EXCLUDES = frozenset({'.git', '.venv', 'venv', 'node_modules', '__pycache__'})


@dataclass(frozen=True)
class FileRecord:
    path: str
    absolute_path: Path = field(repr=False)
    size: int
    mtime_ns: int
    device: int
    inode: int

    @property
    def fingerprint(self) -> tuple[int, int, int, int]:
        return self.device, self.inode, self.size, self.mtime_ns


@dataclass
class ScanResult:
    records: list[FileRecord] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=lambda: {'excluded': 0, 'links': 0, 'hardlinks': 0})
    issues: list[dict[str, str]] = field(default_factory=list)
    invalid_root: bool = False


def is_link_or_reparse(metadata) -> bool:
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)
    )


def issue_kind(error: OSError) -> str:
    return 'permission_denied' if isinstance(error, PermissionError) else 'unreadable'


def scan_directory(root: Path, exclude: tuple[str, ...]) -> ScanResult:
    result = ScanResult()
    root = Path(root).absolute()
    try:
        metadata = root.lstat()
    except (OSError, ValueError) as error:
        result.invalid_root = True
        result.issues.append({'path': '.', 'kind': issue_kind(error)})
        return result
    if is_link_or_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
        result.invalid_root = True
        result.issues.append({'path': '.', 'kind': 'unreadable'})
        return result
    stack = [(root, '', metadata.st_dev, metadata.st_ino)]
    identities = set()
    while stack:
        directory, relative, device, inode = stack.pop()
        try:
            current = directory.lstat()
            if is_link_or_reparse(current):
                result.skipped['links'] += 1
                continue
            if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != (device, inode):
                result.issues.append({'path': relative or '.', 'kind': 'changed'})
                continue
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
        except OSError as error:
            result.issues.append({'path': relative or '.', 'kind': issue_kind(error)})
            continue
        directories = []
        for entry in entries:
            path = directory / entry.name
            rel = f'{relative}/{entry.name}' if relative else entry.name
            try:
                # Path.lstat supplies reliable identity on Windows, where cached
                # DirEntry.stat metadata may omit device/inode information.
                metadata = path.lstat()
            except OSError as error:
                result.issues.append({'path': rel, 'kind': issue_kind(error)})
                continue
            if is_link_or_reparse(metadata):
                result.skipped['links'] += 1
                continue
            if any(fnmatchcase(entry.name, pattern) or fnmatchcase(rel, pattern) for pattern in exclude):
                result.skipped['excluded'] += 1
                continue
            if stat.S_ISDIR(metadata.st_mode):
                if entry.name in DEFAULT_EXCLUDES:
                    result.skipped['excluded'] += 1
                else:
                    directories.append((path, rel, metadata.st_dev, metadata.st_ino))
            elif stat.S_ISREG(metadata.st_mode):
                identity = metadata.st_dev, metadata.st_ino
                if metadata.st_ino > 0 and identity in identities:
                    result.skipped['hardlinks'] += 1
                    continue
                if metadata.st_ino > 0:
                    identities.add(identity)
                result.records.append(FileRecord(rel, path, metadata.st_size, metadata.st_mtime_ns,
                                                 metadata.st_dev, metadata.st_ino))
        stack.extend(reversed(directories))
    result.records.sort(key=lambda record: record.path)
    result.issues.sort(key=lambda issue: (issue['path'], issue['kind']))
    return result


def build_report(scan: ScanResult, top: int, duplicates_checked: bool = False) -> dict:
    extensions: dict[str, dict] = {}
    for record in scan.records:
        extension = Path(record.path).suffix.lower() or '(no extension)'
        group = extensions.setdefault(extension, {'extension': extension, 'files': 0, 'bytes': 0})
        group['files'] += 1
        group['bytes'] += record.size
    largest = sorted(scan.records, key=lambda record: (-record.size, record.path))[:top]
    return {
        'schema_version': 1, 'complete': not scan.issues, 'duplicates_checked': duplicates_checked,
        'files': len(scan.records), 'total_bytes': sum(record.size for record in scan.records),
        'extensions': sorted(extensions.values(), key=lambda group: (-group['bytes'], group['extension'])),
        'largest': [{'path': record.path, 'bytes': record.size} for record in largest],
        'duplicates': [], 'duplicate_bytes': 0, 'skipped': dict(scan.skipped), 'issues': list(scan.issues),
    }
