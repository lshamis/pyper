#!/usr/bin/env python3

import argparse
import importlib
import importlib.util
import os
import random
import re
import string
import sys


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
    if not try_import(module_name):
        return False
    seen.add(module_name)
    return True


class Context:
    def __init__(self, args):
        self.args = args
        self.had_err = False
        self._symbols = {}

    def get_symbols(self, **kwargs):
        public_modules = {k: v for k, v in sys.modules.items() if not k.startswith("_")}
        return dict(public_modules, **self._symbols, **kwargs)

    def _random_module_name(self):
        name = None
        while not name or name in sys.modules:
            name = "_" + "".join(
                random.choice(string.ascii_lowercase) for i in range(10)
            )
        return name

    def load_symbols(self, path):
        path = os.path.expanduser(path)
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        module_name = self._random_module_name()
        spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self._symbols.update(**module.__symbols__)

    def try_load_symbols(self, path):
        try:
            self.load_symbols(path)
            return True
        except:
            return False

    def load_user_symbols(self):
        env_path = os.environ.get("PY_SYMBOL_FILEPATHS")
        if env_path:
            for path in env_path.split(":"):
                self.load_symbols(path)

        self.try_load_symbols("~/.config/py/extra_symbols.py")


class Value:
    def __init__(self, x=Skip, i=Skip):
        self.x = x
        self.i = i


def eval_code(ctx, value, code):
    extra_symbols = {
        name: sym
        for name, sym in {"x": value.x, "i": value.i}.items()
        if sym is not Skip
    }

    while True:
        try:
            # Try x.code()
            if value.x is not Skip:
                attr = getattr(value.x, code, Skip)
                if attr is not Skip:
                    return Value(attr() if callable(attr) else attr, value.i)

            # Execute code.
            result = eval(code, ctx.get_symbols(**extra_symbols))

            # Try code(x)
            if callable(result):
                result = result() if value.x is Skip else result(value.x)

            return Value(result, value.i)
        except NameError as err:
            module_match = re.match("name '(\w*)' is not defined", str(err))
            if module_match:
                if new_import_successful(module_match.group(1)):
                    continue
            ctx.had_err = 1
            return Value(err, value.i)
        except AttributeError as err:
            submodule_match = re.match(
                "module '([\w.]*)' has no attribute '(\w*)'", str(err)
            )
            if submodule_match:
                module_name, submodule_name = submodule_match.groups()
                if new_import_successful(f"{module_name}.{submodule_name}"):
                    continue
            ctx.had_err = 1
            return Value(err, value.i)
        except Exception as err:
            ctx.had_err = 1
            return Value(err, value.i)


def input_stream():
    if sys.stdin.isatty():
        yield Value()
        return

    for i, x in enumerate(sys.stdin):
        yield Value(x.rstrip("\n"), i)


def code_mutator(ctx, instream, code):
    for val in instream:
        if isinstance(val.x, Exception):
            yield val
            continue

        new_val = eval_code(ctx, val, code)

        if isinstance(new_val.x, Exception):
            if ctx.args.show_error:
                yield new_val
        elif new_val.x is None:
            if ctx.args.show_none:
                yield new_val
        elif type(new_val.x) is bool:
            if ctx.args.show_bool:
                yield new_val
            elif new_val.x:
                yield val
        else:
            yield new_val


def xargs(instream):
    yield Value([val.x for val in instream])


def unxargs(instream):
    output_values = next(instream).x
    for x in output_values:
        yield Value(x)


def select_mutator(ctx, instream, code):
    if code == "xargs":
        return xargs(instream)
    elif code == "unxargs":
        return unxargs(instream)
    else:
        return code_mutator(ctx, instream, code)


def print_stream(ctx, stream):
    for val in stream:
        # Errors defaults to filtering out the entry, unless args.show_error.
        if isinstance(val.x, Exception):
            if ctx.args.show_error:
                print(val.x)
        # None defaults to filtering out the entry, unless args.show_none.
        elif val.x is None:
            if ctx.args.show_none:
                print(val.x)
        else:
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
    parser.add_argument(
        "-n",
        "--show-none",
        action="store_true",
        help="Print None values. Default is to use None as a filter.",
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
