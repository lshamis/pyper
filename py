#!/usr/bin/env python3

import argparse
import importlib
import importlib.util
import os
import random
import re
import string
import sys
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


class Context:
    def __init__(self, args):
        self.args = args
        self.had_err = False
        self._symbols = {}

    def user_symbols(self):
        return self._symbols

    def module_symbols(self):
        return {k: v for k, v in sys.modules.items()}

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

    def general_symbols(self, ctx):
        return {
            **ctx.user_symbols(),
            **ctx.module_symbols(),
        }

    def all_symbols(self, ctx):
        return {
            **self.general_symbols(ctx),
            **self.symbols,
            **({"x": self.x} if self.x is not Skip else {}),
            **({"i": self.i} if self.i is not Skip else {}),
        }


def eval_code(ctx, value, code):
    while True:
        try:
            # Try x.code()
            if value.x is not Skip:
                attr = getattr(value.x, code, Skip)
                if attr is not Skip:
                    return value.but_with(x=attr() if callable(attr) else attr)

            # Execute code.
            symbols = value.all_symbols(ctx)
            try:
                result = eval(code, symbols)
            except SyntaxError:
                result = exec(code, symbols)

            # Try code(x)
            if callable(result):
                result = result() if value.x is Skip else result(value.x)

            base_symbols = value.general_symbols(ctx)
            new_symbols = {
                name: sym
                for name, sym in symbols.items()
                if name not in base_symbols and not name.startswith("__")
            }
            value.symbols = {**value.symbols, **new_symbols}
            return value.but_with(x=result)
        except NameError as err:
            module_match = re.match("name '(\w*)' is not defined", str(err))
            assert module_match
            if new_import_successful(module_match.group(1)):
                continue
            ctx.had_err = 1
            return value.but_with(x=err)
        except AttributeError as err:
            submodule_match = re.match(
                "module '([\w.]*)' has no attribute '(\w*)'", str(err)
            )
            assert submodule_match
            module_name, submodule_name = submodule_match.groups()
            if new_import_successful(f"{module_name}.{submodule_name}"):
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
        if val.x is not Skip:
            x.append(val.x)

        if symbols is Skip:
            symbols = dict(**val.symbols)
        else:
            for name, sym in val.symbols.items():
                if name in symbols and symbols[name] != sym:
                    del symbols[name]

    yield Value(x=x, symbols=symbols)


def unxargs(instream):
    try:
        value = next(instream)
    except StopIteration:
        return

    if not isinstance(value.x, typing.Iterable):
        yield value
        return

    for x in value.x:
        yield value.but_with(x=x, i=Skip)


def select_mutator(ctx, instream, code):
    if code == "xargs":
        return xargs(instream)
    elif code == "unxargs":
        return unxargs(instream)
    else:
        return code_mutator(ctx, instream, code)


def print_stream(ctx, stream):
    for val in stream:
        if val.x is Skip:
            continue

        # Errors defaults to filtering out the entry, unless args.show_error.
        if not isinstance(val.x, Exception) or ctx.args.show_error:
            print(val.x)


def main():
    parser = argparse.ArgumentParser()
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
        help="Print raised exceptions. Default is to skip.",
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
    print_stream(ctx, stream)

    return 1 if ctx.had_err else 0


if __name__ == "__main__":
    sys.exit(main())
