# Notes

No open items. (2026-06-10)

Current state: v0.1.0, distribution `pyper-pipe`, module `pyper`, command
`py`. 34 tests (`uv run pytest`), ruff clean (`uv run ruff check`), CI in
`.github/workflows/ci.yml` (pytest on 3.9–3.14 + ruff). Startup ~34ms for
builtin-only expressions; ~0.3s per 100k rows of `int(x)+1`.

## Decisions / rejected ideas — don't re-add without new evidence

- **`-j/--jobs` threaded row evaluation.** Built, benchmarked, reverted
  (see e1eeef0 and its revert 7eb8d55). Numbers on a GIL build: CPU-bound
  rows ~11x slower with threads; reading+splitting 275MB of files was 2x
  slower with -j16 even with a *cold* ext4 cache (NVMe readahead hides IO;
  decode and split dominate). Only genuinely latency-bound rows won
  (HTTP @ 50ms: 7x). Users would assume "more jobs = faster" without
  benchmarking and pessimize the common case. Revisit only for free-threaded
  Python. For IO-bound one-offs, `xargs -P` around `py` works.

- **User symbols files (`PY_SYMBOL_FILEPATHS` / `~/.config/py/`).** Dropped
  after the `_` symbols became built-in: unused in practice, and a config
  concept on the learning curve. Auto-import already gives access to any
  installed module.

- **JSON shorthand flag.** Rejected: `py json.loads 'x["field"]'` already
  works via auto-import; a flag would be a second way to do the same thing
  and one more thing to learn.

- **`unxargs` error-row provenance** (row index is reset to Skip when rows
  pass through). Dropped as not worth the plumbing; `-e` messages just omit
  the row number in that case.

- **Per-row perf below ~3us.** The remaining costs are one C-level
  `dict(base)` copy (~1us) and interpreter/generator overhead. Investigated
  and rejected: dict-subclass globals with `__missing__` (defeats LOAD_GLOBAL
  inline caches; eval gets ~6x slower), shared mutable namespace with
  journal/rollback (breaks lazy closures/genexps that outlive their row).

- **PyPI name.** "pyper" is taken by an unrelated concurrency library;
  distribution is `pyper-pipe` (command stays `py`, module stays `pyper`).

Day-one work (packaging, error-model redesign, unxargs flatten fix, perf:
2.1s -> 0.3s per 100k rows and 75ms -> 34ms startup, --strict, -n,
--version, built-in `_` symbols, lint) is recorded in git history —
`git log --oneline` from 7e3f251 onward.
