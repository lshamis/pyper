# TODO

## P1 — correctness / trust
- [ ] **Auto-import retry double-evaluates expressions.** On `NameError`, the
      importer imports the module and re-`eval`s the *whole* expression, so any
      side effects before the failing name run twice
      (e.g. `py 'do_thing() or json.dumps(x)'`). Fix: pre-scan names
      (`ast.parse` + walk for `Name`/`Attribute` roots) and import before the
      first eval. At minimum, document the caveat in the README.
- [ ] **Exit-code/diagnostic story for errors.** Errors are silently dropped
      without `-e`; only the exit code hints something went wrong. Consider a
      one-line summary on stderr ("skipped N lines with errors; rerun with -e").

## P2 — performance
- [x] **Per-line symbol-table rebuild was ~70% of runtime.** (Fixed
      2026-06-10.) `xargs` itself was already linear (400k lines in 0.26s);
      the old "O(n^2) in xargs" report did not reproduce. The real costs were
      `eval_code` re-merging all of `sys.modules` per row and re-compiling the
      expression string per row. Now: persistent base namespace (user symbols
      + lazily auto-imported modules) copied once per eval, key-diff for
      assignment detection, cached compiled code objects, identity shortcut in
      the xargs symbol merge. 100k rows of `int(x)+1`: 2.1s -> 0.78s.
- [ ] Remaining per-row cost is the `dict(base)` copy (O(|base|), ~250
      entries with extra_symbols loaded). Could be eliminated by evaluating in
      a shared namespace and rolling back new keys, at the cost of trickier
      isolation semantics. Only worth it if multi-100k-row pipes feel slow.

## P3 — features
- [ ] `-n` / no-stdin flag for pure generation (currently relies on
      `isatty()`, which misbehaves under subprocess/cron where stdin is a pipe
      but empty-by-intent).
- [ ] First-class JSON: `py json.loads 'x["field"]'` works today, but a
      shorthand (`-j`?) for per-line JSON in/out would cover a very common
      case.
- [ ] `--version` flag (read from package metadata via `importlib.metadata`).
- [ ] Install `extra_symbols.py` as package data with a post-install hint, so
      it doesn't need to be hand-copied to `~/.config/py/`.

## P4 — project hygiene
- [ ] CI (GitHub Actions): pytest across supported Pythons (3.9–3.14) + a lint
      step (ruff).
- [ ] PyPI name "pyper" is taken by an unrelated concurrency library. Pick a
      distribution name (e.g. `pyper-pipe`) before publishing; the command can
      stay `py`.
- [ ] Add `.gitignore` (`__pycache__/`, `.pytest_cache/` are currently
      committed/untracked noise).
