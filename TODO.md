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
- [ ] **Per-line symbol-table rebuild is ~70% of runtime.** Measured
      2026-06-10: `xargs` itself is linear (400k lines in 0.26s), so the old
      "O(n^2) in xargs" report does not reproduce. The real cost is
      `eval_code` calling `module_symbols()` (full copy of `sys.modules`)
      twice per line plus three dict merges (cProfile, 100k lines of
      `int(x)`: 1.12s of 1.56s in symbol plumbing). Fix: build the base
      symbols dict once, invalidate when `new_import_successful` fires (and/or
      when `len(sys.modules)` changes); detect new user symbols by key
      snapshot instead of full dict diff.

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
