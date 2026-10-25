# folder-report

Find where a directory's logical bytes are going, without changing its contents.

Python 3.11 or newer; no runtime dependencies.

```sh
python -m folder_report ./sample-files --top 10
```

Install from a checkout with `python -m pip install .`, then use `folder-report` with the same arguments.

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

## Development

```sh
python -m unittest discover -s tests -v
```

MIT licensed; see [LICENSE](LICENSE).
