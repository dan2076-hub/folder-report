"""CLI formatting and exit codes."""
import argparse
from pathlib import Path
import sys

from .core import build_report, scan_directory


def nonnegative(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError('must be a nonnegative integer') from None
    if number < 0:
        raise argparse.ArgumentTypeError('must be a nonnegative integer')
    return number


def format_text(report: dict) -> str:
    lines = [f"Files: {report['files']}", f"Logical bytes: {report['total_bytes']}", 'Extensions:']
    lines.extend(f"  {row['extension']}: {row['files']} files, {row['bytes']} bytes" for row in report['extensions'])
    lines.append('Largest files:')
    lines.extend(f"  {row['bytes']:>12}  {row['path']}" for row in report['largest'])
    lines.append('Duplicate detection: not requested')
    lines.append('Skipped: ' + ', '.join(f'{key}={value}' for key, value in report['skipped'].items()))
    lines.extend(f"Issue: {row['path']} ({row['kind']})" for row in report['issues'])
    lines.append('Complete' if report['complete'] else 'Incomplete')
    return '\n'.join(lines)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='Read-only directory size report using logical bytes.')
    parser.add_argument('root', type=Path, help='Directory to inspect')
    parser.add_argument('--top', type=nonnegative, default=10, help='Largest file rows, 0 to hide (default: 10)')
    args = parser.parse_args(argv)
    scan = scan_directory(args.root, ())
    report = build_report(scan, args.top)
    print(format_text(report))
    return 2 if scan.invalid_root else (0 if report['complete'] else 1)
