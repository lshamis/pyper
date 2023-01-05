import collections
import glob
import inspect
import math
import os.path
import pprint
import random
import string
import textwrap

__symbols__ = {}

for mod in [collections, glob, math, os.path, pprint, random, string, textwrap]:
    for name in dir(mod):
        if name.startswith("_"):
            continue
        attr = getattr(mod, name)
        if inspect.ismodule(attr):
            continue
        if f"_{name}" in __symbols__:
            continue
        __symbols__[f"_{name}"] = attr
