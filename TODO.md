# TODO

Current state (2026-06-10): v0.1.0, installed via `uv tool install -e .`.
34 tests (`uv run pytest`), ruff clean (`uv run ruff check`). Startup ~34ms
for builtin-only expressions; ~0.3s per 100k rows of `int(x)+1`.

## Open

### P3 — features
- [ ] Error rows that pass through `unxargs` lose their row index (`i` is
      reset); consider carrying source-row provenance for better -e messages.
- [ ] First-class JSON: `py json.loads 'x["field"]'` works today, but a
      shorthand for per-line JSON in/out would cover a very common case.
      (Don't use `-j`; that letter is burned, see Rejected.)

### P4 — project hygiene
- [ ] CI (GitHub Actions): pytest across supported Pythons (3.9–3.14) + ruff
      check/format. Config and dev dependency group are already in pyproject;
      only the workflow file is missing.
- [ ] PyPI name "pyper" is taken by an unrelated concurrency library. Pick a
      distribution name (e.g. `pyper-pipe`) before publishing; the command can
      stay `py`.

### Perf — only if someone streams millions of rows
- [ ] What's left per row: one C-level `dict(base)` copy (~1us) and
      generator/interpreter overhead. Investigated and rejected: dict-subclass
      globals with `__missing__` fallback (defeats LOAD_GLOBAL inline caches —
      eval itself gets ~6x slower, a net wash); shared mutable namespace with
      journal/rollback (breaks lazy closures/genexps that outlive their row).

## Done (all 2026-06-10)

### Correctness / behavior
- [x] **Errors are diagnostics, not data.** Error rows never reach stdout.
      Default: dropped + one-line stderr summary ("py: skipped N row(s) with
      errors; rerun with -e to see them") + exit 1. With `-e`: each error on
      stderr as `py: row N: ExcType: message`. Error rows flow *around*
      xargs (not folded into the collection) and through unxargs.
- [x] **unxargs flattens every row.** It used to consume only the first row
      and silently discard the rest of the stream. str/bytes are atomic (no
      char explosion).
- [x] **Auto-import no longer double-evaluates.** Expression ASTs are scanned
      once; referenced modules (incl. dotted submodule chains) import before
      first eval. NameError/AttributeError retry remains only for
      dynamically-constructed names, where a side effect can still repeat.
- [x] BrokenPipeError (e.g. `| head`) exits quietly; Ctrl-C exits 130.
- [x] User symbols shadow same-named modules; assignment re-binding across
      expressions works (`a=x` ... `a=y`); `del` of a seeded name is safe.

### Performance (baseline -> final, 100k rows, extra_symbols installed)
- [x] `'int(x)+1'`: 2.1s -> 0.31s; `'y=int(x)' 'y'`: 4.0s -> 0.60s.
      The "O(n^2) in xargs" report did not reproduce (xargs was linear all
      along). Actual fixes: persistent base namespace instead of re-merging
      sys.modules per row; compiled-code cache; capture new symbols off the
      dict tail only when eval grew the namespace; identity shortcut in the
      xargs symbol merge.
- [x] Startup 75ms -> 34ms (builtin-only expressions): hand-rolled arg parser
      (argparse + transitive re/enum cost ~30ms), cold-path imports inlined,
      `_` symbols built lazily on first unresolvable name.

### Features / hygiene
- [x] `-s/--strict`: abort on the first row error (reported on stderr, exit
      1); aggregates can never silently cover partial data.
- [x] Built-in `_`-prefixed symbols replace the extra_symbols.py config file
      entirely; the PY_SYMBOL_FILEPATHS user-symbols-file mechanism was then
      dropped too (unused in practice, one less concept to learn). If custom
      symbols ever come back, prefer something zero-config like reading a
      single well-known file with plain assignments.
- [x] `-n/--no-input`: ignore stdin, evaluate once (cron/subprocess case).
- [x] `--version`, single-sourced from `pyper.__version__`.
- [x] Packaged: pyproject + console-script entry point (`uv tool install`),
      replacing the copy-the-file install. Module renamed py -> pyper.py.
- [x] ruff lint+format config in pyproject; repo clean; dev dependency group
      (pytest, ruff) so `uv run pytest` works bare; .gitignore.

## Rejected (with data — don't re-add without new evidence)
- **`-j/--jobs` threaded row evaluation.** Built, benchmarked, reverted
  2026-06-10 (see e1eeef0 and its revert 7eb8d55). Numbers on a GIL build:
  CPU-bound rows ~11x slower with threads; reading+splitting 275MB of files
  was 2x slower with -j16 even with a *cold* ext4 cache (NVMe readahead hides
  IO; decode and split dominate). Only genuinely latency-bound rows won
  (HTTP @ 50ms: 7x). Verdict: users would assume "more jobs = faster" without
  benchmarking and pessimize the common case; the one winning workload is
  niche. Revisit only for free-threaded Python, where CPU-bound rows would
  actually parallelize. For IO-bound one-offs, `xargs -P` around `py` remains
  a workaround.
