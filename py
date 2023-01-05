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

    def eval_code(self, code, value=None, **extra_symbols):
        while True:
            try:
                # Try value.code()
                attr = getattr(value, code, Skip)
                if attr is not Skip:
                    return attr() if callable(attr) else attr

                # Execute code.
                result = eval(code, self.get_symbols(**extra_symbols))

                # Try code(value)
                if callable(result):
                    result = result(value)

                return result
            except NameError as err:
                module_match = re.match("name '(\w+)' is not defined", str(err))
                if module_match and try_import(module_match.group(1)):
                    continue
                self.had_err = 1
                return err
            except AttributeError as err:
                submodule_match = re.match(
                    "module '([\w.]+)' has no attribute '(\w+)'", str(err)
                )
                if submodule_match:
                    module_name, submodule_name = submodule_match.groups()
                    if try_import(f"{module_name}.{submodule_name}"):
                        continue
                self.had_err = 1
                return err
            except Exception as err:
                self.had_err = 1
                return err


class NoValueHandler:
    def __init__(self, ctx):
        self.ctx = ctx

    def eval(self, code):
        return OneValueHandler(self.ctx, self.ctx.eval_code(code))

    def print(self):
        pass


class OneValueHandler:
    def __init__(self, ctx, value):
        self.ctx = ctx
        self.value = value

    def eval(self, code):
        if code == "unxargs":
            return ManyValueHandler(self.ctx, self.value)

        if isinstance(self.value, Exception):
            return self

        return OneValueHandler(
            self.ctx, self.ctx.eval_code(code, value=self.value, x=self.value)
        )

    def print(self):
        # Errors defaults to filtering out the entry, unless args.show_error.
        if isinstance(self.value, Exception):
            if self.ctx.args.show_error:
                print(self.value)
        # None defaults to filtering out the entry, unless args.show_none.
        elif self.value is None:
            if self.ctx.args.show_none:
                print(self.value)
        else:
            print(self.value)


class ManyValueHandler:
    def __init__(self, ctx, values, indexes=None):
        self.ctx = ctx
        self.values = values
        self.indexes = indexes

    def eval(self, code):
        if code == "xargs":
            return OneValueHandler(self.ctx, self.values)

        if isinstance(self.values, Exception):
            return self

        if self.indexes is None:
            new_vals = [self._eval_one(code, val) for val in self.values]
            new_vals = [nval for nval in new_vals if nval is not Skip]
            return ManyValueHandler(self.ctx, new_vals)

        new_vals = [
            self._eval_one(code, val, idx)
            for val, idx in zip(self.values, self.indexes)
        ]

        new_val_idx = [
            (nval, idx) for nval, idx in zip(new_vals, self.indexes) if nval is not Skip
        ]

        if not new_val_idx:
            return ManyValueHandler(self.ctx, [])

        return ManyValueHandler(self.ctx, *zip(*new_val_idx))

    def _eval_one(self, code, val, idx=None):
        if isinstance(val, Exception):
            if self.ctx.args.show_error:
                return val
        elif val is None:
            if self.ctx.args.show_none:
                return val
        else:
            local_symbols = {"x": val}
            if idx:
                local_symbols["i"] = idx
            new_val = self.ctx.eval_code(code, value=val, **local_symbols)
            if isinstance(new_val, Exception):
                if self.ctx.args.show_error:
                    return new_val
            elif new_val is None:
                if self.ctx.args.show_none:
                    return new_val
            elif type(new_val) is bool:
                if self.ctx.args.show_bool:
                    return new_val
                elif new_val:
                    return val
            else:
                return new_val

        return Skip

    def print(self):
        if isinstance(self.values, Exception):
            if self.ctx.args.show_error:
                print(self.values)
            return

        for val in self.values:
            OneValueHandler(self.ctx, val).print()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("expr", help="Expression to apply to all inputs.")
    parser.add_argument(
        "xargs",
        action="store",
        nargs="*",
        help="Grouped arguments generated by shell xargs.",
    )
    parser.add_argument(
        "-t",
        "--then",
        action="append",
        help="Additional expression to apply to all inputs.",
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

    if sys.stdin.isatty():
        value_handler = NoValueHandler(ctx)
    elif ctx.args.xargs:
        value_handler = OneValueHandler(ctx, ctx.args.xargs)
    else:
        values = [val.rstrip("\n") for val in sys.stdin]
        value_handler = ManyValueHandler(ctx, values, range(len(values)))

    value_handler = value_handler.eval(ctx.args.expr)
    for expr in ctx.args.then or []:
        value_handler = value_handler.eval(expr)
    value_handler.print()

    return 1 if ctx.had_err else 0


if __name__ == "__main__":
    sys.exit(main())
