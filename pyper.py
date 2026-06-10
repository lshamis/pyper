#!/usr/bin/env python3

import argparse
import ast
import builtins
import importlib
import importlib.util
import os
import random
import re
import string
import sys
import types
import typing


class Skip:
    pass


def try_import(module_name):
    try:
        return importlib.import_module(module_name)
    except Exception:
        return None


def new_import_successful(module_name, seen=set()):
    if module_name in seen:
        return False
    seen.add(module_name)
    if not try_import(module_name):
        return False
    return True


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
        name = None
        while not name or name in sys.modules:
            name = "_" + "".join(
                random.choice(string.ascii_lowercase) for i in range(10)
            )
        return name

    def load_symbols(self, path):
        module_name = self._random_module_name()
        spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self._symbols.update(**module.__symbols__)
        self._base = None

    def load_user_symbols(self):
        env_path = os.environ.get(
            "PY_SYMBOL_FILEPATHS", "~/.config/py/extra_symbols.py"
        )
        for path in env_path.split(":"):
            path = os.path.expanduser(path)
            if os.path.exists(path):
                self.load_symbols(path)


class Value:
    def __init__(self, x=Skip, i=Skip, symbols=Skip):
        self.x = x
        self.i = i
        self.symbols = symbols if symbols is not Skip else {}

    def but_with(self, **kwargs):
        return Value(
            x=kwargs.get("x", self.x),
            i=kwargs.get("i", self.i),
            symbols=kwargs.get("symbols", self.symbols),
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
            symbols.update(value.symbols)
            if value.x is not Skip:
                symbols["x"] = value.x
            if value.i is not Skip:
                symbols["i"] = value.i
            result = eval(ctx.compiled(code), symbols)

            # Try code(x)
            if callable(result):
                result = result() if value.x is Skip else result(value.x)

            new_symbols = {
                name: symbols[name]
                for name in symbols.keys() - base.keys()
                if not name.startswith("__")
            }
            value.symbols = {**value.symbols, **new_symbols}
            return value.but_with(x=result)
        except NameError as err:
            module_match = re.match(r"name '(\w*)' is not defined", str(err))
            if module_match and new_import_successful(module_match.group(1)):
                ctx.add_module(module_match.group(1))
                continue
            ctx.had_err = 1
            return value.but_with(x=err)
        except AttributeError as err:
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


def input_stream():
    if sys.stdin.isatty():
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
        if not isinstance(value.x, typing.Iterable) or isinstance(
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


def main():
    parser = argparse.ArgumentParser(prog="py")
    parser.add_argument(
        "expr",
        action="store",
        nargs="+",
        help="Expression to apply to all inputs.",
    )
    parser.add_argument(
        "-e",
        "--show-error",
        action="store_true",
        help="Report each raised exception on stderr."
        " Default is to skip, with a summary on stderr.",
    )
    parser.add_argument(
        "-b",
        "--show-bool",
        action="store_true",
        help="Print bool values. Default is to use bool values as a filter.",
    )
    ctx = Context(parser.parse_intermixed_args())
    ctx.load_user_symbols()

    stream = input_stream()
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
