# folder-report

Find where a directory's logical bytes are going, without changing its contents.

Python 3.11 or newer; no runtime dependencies.

[Русский](README.ru.md)

```sh
python -m folder_report ./sample-files --top 10
```

Install from a checkout with `python -m pip install .`, then use `folder-report` with the same arguments.

```sh
git clone https://github.com/dan2076-hub/folder-report.git
cd folder-report
python -m pip install .
folder-report ./sample-files --duplicates --json
```

Reports total files/bytes, extension groups and largest files. `--top 0` hides largest-file rows. Paths are root-relative, use forward slashes and have stable ordering. Ordinary hidden files are included.

Directories named `.git`, `.venv`, `venv`, `node_modules` and `__pycache__` are excluded by default. Symlinks and Windows reparse points (including junctions) are skipped. Hard-link aliases count once when the filesystem supplies reliable device/inode identity.

Sizes are logical file lengths, not allocated disk usage.

## Verified duplicates and exclusions

```sh
folder-report ./sample-files --duplicates --exclude "*.tmp" --exclude "cache/*"
```

Duplicate detection is opt-in. Files are grouped by size, then SHA-256 hashed in 1 MiB chunks, then compared byte by byte. Unique-size files are not hashed. Hash equality alone never establishes duplicates. Hard-link aliases do not inflate counts. Empty duplicate files contribute zero bytes.

Each group of N files of size S contributes `(N - 1) * S` duplicate logical bytes. This is not a guarantee of reclaimable physical space on compressed, deduplicated or shared filesystems.

`--exclude` is repeatable. Patterns use case-sensitive `fnmatch` against a basename or relative POSIX path; `*` can match a slash. This is not a `.gitignore` parser. Default directory exclusions remain active.

Metadata (device, inode, length and modification time) is checked against the scan record before/after reading, on both open handles and final paths. Changed or unavailable files produce issues and an incomplete report. The scan is not an atomic snapshot or a security boundary against concurrent hostile changes.

Exit codes: `0` complete, `1` partial scan, `2` invalid root/arguments. No files are deleted, moved, renamed or modified. Output goes to stdout.

## JSON reports

```sh
folder-report ./sample-files --duplicates --exclude "*.tmp" --json > ../folder-report.json
```

Redirect reports outside the inspected tree, so the output file does not become part of the scan. The JSON object has schema version 1. Handled root and runtime errors also produce JSON; argparse usage errors retain their normal stderr diagnostic and exit 2.

For `a.txt=hello`, `b.txt=hello`, `c.txt=world` (each five bytes):

```json
{
  "schema_version": 1,
  "complete": true,
  "duplicates_checked": true,
  "files": 3,
  "total_bytes": 15,
  "extensions": [{"extension": ".txt", "files": 3, "bytes": 15}],
  "largest": [{"path": "a.txt", "bytes": 5}, {"path": "b.txt", "bytes": 5}, {"path": "c.txt", "bytes": 5}],
  "duplicates": [{"bytes_each": 5, "paths": ["a.txt", "b.txt"], "duplicate_bytes": 5}],
  "duplicate_bytes": 5,
  "skipped": {"excluded": 0, "links": 0, "hardlinks": 0},
  "issues": []
}
```

Without `--duplicates`, `duplicates_checked` is false and duplicate fields are empty/zero. Duplicate detection can succeed and return exit 0 even when duplicates exist. Inspect `complete` and the exit code before relying on totals; inaccessible directories may hide files.

Issues use relative paths and the kinds `permission_denied`, `changed` or `unreadable`. Missing/non-directory roots use path `.` and exit 2; partial access/read/change failures use exit 1. Invalid roots, including root symlinks/reparse points, are not followed. File identities and absolute paths are internal and are not serialized.

Extension groups use the lowercased final suffix or `(no extension)`, sorted by decreasing bytes then extension. Largest files use decreasing bytes then relative path. Skipped counters count excluded entries, link entries, and extra hard-link aliases respectively. Special non-regular files are ignored. When identity is unavailable, paths may count separately; logical duplicate bytes remain an estimate, not a physical-space promise.

Reading can update filesystem-managed access times. File contents and modification times are not changed. Memory usage grows with the number of scanned files; file contents are streamed in chunks. No cleanup, image similarity, archive unpacking or network upload is performed.

## Development

```sh
python -m unittest discover -s tests -v
python -m pip wheel --no-deps . --wheel-dir dist
```

GitHub Actions runs Windows/Linux with Python 3.11 and 3.13. Tests cover hash collisions, content changes during reading, deterministic sorting, hard links, simulated permissions/reparse points, Unicode, and input preservation. Real symlink tests skip only if link creation is unsupported or not permitted.

MIT licensed; see [LICENSE](LICENSE).
