#!/usr/bin/env python3

# Startup latency matters for a per-pipe CLI tool; modules that are only
# needed on cold paths (error handling, symbols-file loading) are imported
# inline there instead. Notably argparse is avoided entirely (~30ms).
import ast
import builtins
import collections.abc
import importlib
import itertools
import os
import sys
import types

__version__ = "0.1.0"


class Skip:
    pass


def try_import(module_name):
    try:
        return importlib.import_module(module_name)
    except Exception:
        return None


# Names whose import has already been attempted (hit or miss), so failed
# imports aren't retried for every row.
_attempted_imports = set()


def new_import_successful(module_name):
    if module_name in _attempted_imports:
        return False
    _attempted_imports.add(module_name)
    return try_import(module_name) is not None


def dotted_name_candidates(code):
    """Names (and dotted attribute chains rooted at names) read by `code`.

    E.g. "json.dumps(x)" -> {"json", "json.dumps", "x"}.
    """
    try:
        tree = ast.parse(code, mode="eval")
    except SyntaxError:
        try:
            tree = ast.parse(code, mode="exec")
        except SyntaxError:
            return set()

    candidates = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            parts = []
            cur = node
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name) and isinstance(cur.ctx, ast.Load):
                parts.append(cur.id)
                parts.reverse()
                for k in range(1, len(parts) + 1):
                    candidates.add(".".join(parts[:k]))
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            candidates.add(node.id)
    return candidates


class Context:
    def __init__(self, args):
        self.args = args
        self.had_err = False
        self._symbols = {}
        self._base = None
        self._code_cache = {}
        self._user_symbols_loaded = False

    def compiled(self, code):
        # Compile each expression once instead of per row. eval() happily
        # runs "exec"-mode code objects (returning None), so statements like
        # assignments still work. Compile errors are cached and re-raised so
        # each row reports the error without recompiling.
        entry = self._code_cache.get(code)
        if entry is None:
            try:
                entry = compile(code, "<py>", "eval")
            except SyntaxError:
                try:
                    entry = compile(code, "<py>", "exec")
                except SyntaxError as err:
                    entry = err
            self._code_cache[code] = entry
        if isinstance(entry, SyntaxError):
            raise entry
        return entry

    def base_symbols(self):
        # The persistent eval namespace: user symbols plus any modules pulled
        # in by auto-import. Built once and reused; eval_code copies it per
        # evaluation instead of re-merging all of sys.modules per row.
        if self._base is None:
            self._base = {"__builtins__": __builtins__, **self._symbols}
        return self._base

    def add_module(self, name):
        self.base_symbols()[name] = sys.modules[name]

    def preimport(self, code):
        """Import modules referenced by `code` before it is first evaluated.

        Without this, missing modules are resolved by catching NameError and
        re-evaluating the expression, which repeats any side effects that ran
        before the failing name. Resolving the expression's own (static)
        names up front means that retry path almost never fires. Done once
        per expression, not per row.
        """
        base = self.base_symbols()
        for name in sorted(dotted_name_candidates(code)):
            parts = name.split(".")
            if parts[0] in ("x", "i") or hasattr(builtins, parts[0]):
                continue
            if parts[0] not in base:
                self.ensure_user_symbols()
            if len(parts) == 1:
                if name not in base and new_import_successful(name):
                    self.add_module(name)
                continue
            # Dotted chain: import submodules for attributes that don't
            # resolve (mirrors the runtime AttributeError retry).
            obj = base.get(parts[0], Skip)
            prefix = parts[0]
            for attr in parts[1:]:
                if not isinstance(obj, types.ModuleType):
                    break
                prefix += "." + attr
                nxt = getattr(obj, attr, Skip)
                if nxt is Skip:
                    new_import_successful(prefix)
                    nxt = getattr(obj, attr, Skip)
                if nxt is Skip:
                    break
                obj = nxt

    def _random_module_name(self):
        import random
        import string

        name = None
        while not name or name in sys.modules:
            name = "_" + "".join(
                random.choice(string.ascii_lowercase) for i in range(10)
            )
        return name

    def load_symbols(self, path):
        import importlib.util

        module_name = self._random_module_name()
        spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self._symbols.update(**module.__symbols__)
        if self._base is not None:
            # Update in place: eval_code may hold a reference to the dict.
            self._base.update(module.__symbols__)

    def ensure_user_symbols(self):
        """Load symbols files lazily, on the first unresolvable name.

        Loading (and importing the modules referenced by) the symbols file
        costs ~20ms, which would otherwise be paid on every invocation even
        for expressions made purely of builtins.
        """
        if self._user_symbols_loaded:
            return
        self._user_symbols_loaded = True
        env_path = os.environ.get(
            "PY_SYMBOL_FILEPATHS", "~/.config/py/extra_symbols.py"
        )
        for path in env_path.split(":"):
            path = os.path.expanduser(path)
            if os.path.exists(path):
                self.load_symbols(path)


_KEEP = object()


class Value:
    __slots__ = ("i", "symbols", "x")

    def __init__(self, x=Skip, i=Skip, symbols=Skip):
        self.x = x
        self.i = i
        self.symbols = symbols if symbols is not Skip else {}

    def but_with(self, x=_KEEP, i=_KEEP, symbols=_KEEP):
        return Value(
            x=self.x if x is _KEEP else x,
            i=self.i if i is _KEEP else i,
            symbols=self.symbols if symbols is _KEEP else symbols,
        )


def eval_code(ctx, value, code):
    base = ctx.base_symbols()
    while True:
        try:
            # Try x.code()
            if value.x is not Skip:
                attr = getattr(value.x, code, Skip)
                if attr is not Skip:
                    return value.but_with(x=attr() if callable(attr) else attr)

            # Execute code.
            symbols = dict(base)
            if value.symbols:
                symbols.update(value.symbols)
            if value.x is not Skip:
                symbols["x"] = value.x
            if value.i is not Skip:
                symbols["i"] = value.i
            seeded_len = len(symbols)

            result = eval(ctx.compiled(code), symbols)

            # Try code(x)
            if callable(result):
                result = result() if value.x is Skip else result(value.x)

            # Most expressions don't assign names; only pay for capture when
            # eval grew the namespace. New names can only be *appended*
            # (overwrites don't change dict order), so they are exactly the
            # tail past seeded_len.
            new_symbols = {}
            if len(symbols) > seeded_len:
                for name in itertools.islice(symbols, seeded_len, None):
                    if not name.startswith("__") and name not in ("x", "i"):
                        new_symbols[name] = symbols[name]
            if value.symbols:
                # A name seeded from value.symbols may have been re-assigned
                # in place (e.g. a second 'a = ...'), which appends nothing.
                for name, old in value.symbols.items():
                    cur = symbols.get(name, Skip)
                    if cur is not Skip and cur is not old:
                        new_symbols[name] = cur
            if new_symbols:
                value.symbols = {**value.symbols, **new_symbols}
            return value.but_with(x=result)
        except NameError as err:
            import re

            module_match = re.match(r"name '(\w*)' is not defined", str(err))
            if module_match:
                name = module_match.group(1)
                ctx.ensure_user_symbols()
                if name in base:
                    continue
                if new_import_successful(name):
                    ctx.add_module(name)
                    continue
            ctx.had_err = 1
            return value.but_with(x=err)
        except AttributeError as err:
            import re

            submodule_match = re.match(
                r"module '([\w.]*)' has no attribute '(\w*)'", str(err)
            )
            if submodule_match and new_import_successful(
                "{}.{}".format(*submodule_match.groups())
            ):
                continue
            ctx.had_err = 1
            return value.but_with(x=err)
        except Exception as err:
            ctx.had_err = 1
            return value.but_with(x=err)


def input_stream(ctx):
    if ctx.args.no_input or sys.stdin.isatty():
        yield Value()
        return

    for i, x in enumerate(sys.stdin):
        yield Value(x=x.rstrip("\n"), i=i)


def code_mutator(ctx, instream, code):
    for val in instream:
        if isinstance(val.x, Exception):
            yield val
            continue

        new_val = eval_code(ctx, val, code)

        if new_val.x is None:
            yield val
        elif type(new_val.x) is bool:
            if ctx.args.show_bool:
                yield new_val
            elif new_val.x:
                yield val
        else:
            yield new_val


def xargs(instream):
    x = []
    symbols = Skip
    for val in instream:
        if isinstance(val.x, Exception):
            # Error rows pass through (like every other stage) instead of
            # being folded into the collection.
            yield val
            continue

        if val.x is not Skip:
            x.append(val.x)

        if symbols is Skip:
            symbols = dict(**val.symbols)
        else:
            for name, sym in val.symbols.items():
                if name in symbols:
                    prev = symbols[name]
                    # Identity check first: avoids O(size) equality compares
                    # for large collection-valued symbols.
                    if prev is not sym and prev != sym:
                        del symbols[name]

    yield Value(x=x, symbols=symbols)


def unxargs(instream):
    for value in instream:
        # Non-iterables (including error rows) pass through unchanged.
        # str/bytes are treated as atomic, not as character sequences.
        if not isinstance(value.x, collections.abc.Iterable) or isinstance(
            value.x, (str, bytes)
        ):
            yield value
            continue

        for x in value.x:
            yield value.but_with(x=x, i=Skip)


def select_mutator(ctx, instream, code):
    if code == "xargs":
        return xargs(instream)
    elif code == "unxargs":
        return unxargs(instream)
    else:
        ctx.preimport(code)
        return code_mutator(ctx, instream, code)


def print_stream(ctx, stream):
    skipped_errors = 0
    for val in stream:
        if val.x is Skip:
            continue

        # Errors are diagnostics, not data: they never go to stdout. With
        # --show-error each one is reported on stderr; otherwise they are
        # counted and summarized.
        if isinstance(val.x, Exception):
            if ctx.args.show_error:
                where = f"row {val.i}: " if val.i is not Skip else ""
                print(
                    f"py: {where}{type(val.x).__name__}: {val.x}",
                    file=sys.stderr,
                )
            else:
                skipped_errors += 1
            continue
        print(val.x)

    if skipped_errors:
        print(
            f"py: skipped {skipped_errors} row(s) with errors;"
            " rerun with -e to see them.",
            file=sys.stderr,
        )


USAGE = "usage: py [-h] [--version] [-e] [-b] [-n] expr [expr ...]"
HELP = f"""{USAGE}

positional arguments:
  expr              Expression to apply to all inputs.

options:
  -h, --help        show this help message and exit
  --version         show program's version number and exit
  -e, --show-error  Report each raised exception on stderr. Default is to
                    skip, with a summary on stderr.
  -b, --show-bool   Print bool values. Default is to use bool values as a
                    filter.
  -n, --no-input    Ignore stdin and evaluate the expressions once (useful
                    under cron/subprocesses where stdin is a pipe but not
                    meant as input).
"""


class Args:
    __slots__ = ("expr", "no_input", "show_bool", "show_error")

    def __init__(self):
        self.expr = []
        self.show_error = False
        self.show_bool = False
        self.no_input = False


def usage_error(message):
    print(USAGE, file=sys.stderr)
    print(f"py: error: {message}", file=sys.stderr)
    sys.exit(2)


def parse_args(argv):
    # Hand-rolled (instead of argparse) to keep startup snappy: argparse and
    # its transitive imports (re, enum, ...) cost ~30ms per invocation.
    args = Args()
    flags_done = False
    for tok in argv:
        if flags_done or not tok.startswith("-") or tok == "-":
            args.expr.append(tok)
        elif tok == "--":
            flags_done = True
        elif tok == "--help":
            print(HELP, end="")
            sys.exit(0)
        elif tok == "--version":
            print(f"py {__version__}")
            sys.exit(0)
        elif tok == "--show-error":
            args.show_error = True
        elif tok == "--show-bool":
            args.show_bool = True
        elif tok == "--no-input":
            args.no_input = True
        elif tok.startswith("--"):
            usage_error(f"unrecognized arguments: {tok}")
        else:
            for char in tok[1:]:
                if char == "h":
                    print(HELP, end="")
                    sys.exit(0)
                elif char == "e":
                    args.show_error = True
                elif char == "b":
                    args.show_bool = True
                elif char == "n":
                    args.no_input = True
                else:
                    usage_error(f"unrecognized arguments: {tok}")
    if not args.expr:
        usage_error("the following arguments are required: expr")
    return args


def main():
    ctx = Context(parse_args(sys.argv[1:]))

    stream = input_stream(ctx)
    for expr in ctx.args.expr:
        stream = select_mutator(ctx, stream, expr)
    try:
        print_stream(ctx, stream)
    except BrokenPipeError:
        # Downstream consumer (e.g. `head`) closed the pipe. Exit quietly.
        # Redirect stdout to devnull so the interpreter doesn't raise again
        # while flushing during shutdown.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        return 0
    except KeyboardInterrupt:
        return 130

    return 1 if ctx.had_err else 0


if __name__ == "__main__":
    sys.exit(main())
