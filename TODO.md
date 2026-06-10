# TODO

## P1 — correctness / trust
- [x] **Auto-import retry double-evaluates expressions.** (Fixed 2026-06-10.)
      Each expression's AST is now scanned once and referenced modules
      (including dotted submodule chains) are imported before the first eval.
      The NameError/AttributeError retry remains only as a fallback for
      dynamically-constructed names — a side effect can still repeat in that
      rare case (e.g. `py 'do_thing() or eval("somemod.f()")'`).
- [x] **Exit-code/diagnostic story for errors.** (Fixed 2026-06-10.) Silently
      dropped errors now produce a one-line stderr summary:
      "py: skipped N row(s) with errors; rerun with -e to see them."

## P2 — performance
- [x] **Per-line symbol-table rebuild was ~70% of runtime.** (Fixed
      2026-06-10.) `xargs` itself was already linear (400k lines in 0.26s);
      the old "O(n^2) in xargs" report did not reproduce. The real costs were
      `eval_code` re-merging all of `sys.modules` per row and re-compiling the
      expression string per row. Now: persistent base namespace (user symbols
      + lazily auto-imported modules) copied once per eval, key-diff for
      assignment detection, cached compiled code objects, identity shortcut in
      the xargs symbol merge. 100k rows of `int(x)+1`: 2.1s -> 0.78s.
- [x] **Per-row symbol bookkeeping.** (Fixed 2026-06-10.) The key-set diff and
      but_with plumbing are gone; new symbols are read off the dict tail only
      when eval grew the namespace. 100k rows of `int(x)+1`: 0.31s (was 2.1s
      at the start of the effort); `'y=int(x)' 'y'`: 0.60s (was 4.0s).
- [x] **Startup latency.** (Fixed 2026-06-10.) 75ms -> 34ms for builtin-only
      expressions: argparse replaced with a hand-rolled parser (~30ms of
      transitive imports), re/random/string/importlib.util imported on their
      cold paths only, and symbols files loaded lazily on the first
      unresolvable name (~23ms skipped when unused). Interpreter floor ~21ms.
      Caveat: a symbols file that shadows a *builtin* name won't load for an
      expression that only uses builtins (obscure; prefixed symbols like the
      shipped `_pi` style are unaffected).
- [ ] What's left per row: one C-level `dict(base)` copy (~1us) and
      generator/interpreter overhead. Investigated and rejected: dict-subclass
      globals with `__missing__` fallback (defeats LOAD_GLOBAL inline caches —
      eval itself gets ~6x slower, a net wash); shared mutable namespace with
      journal/rollback (breaks lazy closures/genexps that outlive their row).
      Revisit only if someone actually streams millions of rows.

## P3 — features
- [ ] `--strict` flag: any row error aborts (or poisons aggregates) instead of
      dropping the row. The permissive default can make a partial xargs
      aggregate look complete to a downstream tool that ignores exit codes.
- [ ] Error rows that pass through `unxargs` lose their row index (`i` is
      reset); consider carrying source-row provenance for better -e messages.
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
