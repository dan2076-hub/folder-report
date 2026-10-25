# folder-report

Find where a directory's logical bytes are going, without changing its contents.

Python 3.11 or newer; no runtime dependencies.

```sh
python -m folder_report ./sample-files --top 10
```

Install from a checkout with `python -m pip install .`, then use `folder-report` with the same arguments.

Reports total files/bytes, extension groups and largest files. `--top 0` hides largest-file rows. Paths are root-relative, use forward slashes and have stable ordering. Ordinary hidden files are included.

Directories named `.git`, `.venv`, `venv`, `node_modules` and `__pycache__` are excluded by default. Symlinks and Windows reparse points (including junctions) are skipped. Hard-link aliases count once when the filesystem supplies reliable device/inode identity.

Sizes are logical file lengths, not allocated disk usage. The initial version reports sizes; opt-in duplicate detection is being added separately.

Exit codes: `0` complete, `1` partial scan, `2` invalid root/arguments. No files are deleted, moved, renamed or modified. Output goes to stdout.

## Development

```sh
python -m unittest discover -s tests -v
```

MIT licensed; see [LICENSE](LICENSE).
