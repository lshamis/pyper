# py — a Python pipe helper

`py` makes bash hacking easier by letting you mix Python expressions into
pipes. Each expression is evaluated once per input line, with the line bound
to `x` (and its index to `i`).

```sh
$ ps aux | grep Xorg | py 'x.split()[1]'
24723
24992
```

Expressions chain left to right:
```sh
$ ps aux | grep Xorg | py 'x.split()' 'x[1]'
24723
24992
```

When the evaluation is of the form `x.expr()` or `expr(x)`, the call can be
left implicit:
```sh
$ ps aux | grep Xorg | py split 'x[1]'
24723
24992
```

Modules import themselves — no `import` statements needed:
```sh
$ echo '{"user": "ada", "id": 7}' | py json.loads 'x["user"]'
ada
$ py 'math.tau'
6.283185307179586
```

### xargs and unxargs:
`xargs` switches from one-row-at-a-time to all-rows-as-one-collection;
`unxargs` is its inverse, flattening a collection back into rows:
```sh
$ ps aux | py split 'x[0]' xargs collections.Counter 'x.most_common(3)'
[('root', 334), ('lshamis', 161), ('systemd+', 3)]

$ py 5 range unxargs
0
1
2
3
4
```

### Filtering:
Boolean expressions act as filters (use `-b/--show-bool` to print the bools
instead):
```sh
$ ls / | py 'len(x) > 4'
cdrom
lib64
lost+found
media
swap.img
$ ls / | py -b 'len(x) > 4'
False
False
True
False
...
```

### Errors:
A row whose expression raises is dropped from the output, with a summary on
stderr and exit code 1. `-e` reports every error; `-s` aborts on the first
one (so an aggregate can never silently cover partial data):
```sh
$ seq 3 | py '1/(int(x)-2)'
-1.0
1.0
py: skipped 1 row(s) with errors; rerun with -e to see them.

$ seq 3 | py -e '1/(int(x)-2)'
-1.0
1.0
py: row 1: ZeroDivisionError: division by zero

$ seq 3 | py -s '1/(int(x)-2)'
-1.0
py: row 1: ZeroDivisionError: division by zero
py: --strict: aborting on first error
```
Errors are diagnostics, not data: they only ever go to stderr, so stdout
stays safe to pipe onward.

### Extra symbols:
Public attributes of common stdlib modules (`collections`, `glob`, `math`,
`os.path`, `pprint`, `random`, `string`, `textwrap`) are built in as
first-class symbols, prefixed by an `_`:
```sh
$ py _pi
3.141592653589793
$ py _digits
0123456789
$ ls | py _abspath
/home/lshamis/github/lshamis/pyper/pyper.py
/home/lshamis/github/lshamis/pyper/README.md
$ echo 'Hello, World!' | py '_shorten(x, width=12)'
Hello, [...]
$ echo 'Hello, World!' | py '_wrap(x, width=12)' unxargs
Hello,
World!
```

### Installation:
```sh
$ uv tool install pyper-pipe
```
or from a checkout (editable, so repo edits take effect immediately):
```sh
$ uv tool install --editable .
```
`pipx install` works the same way. Either installs a `py` command into
`~/.local/bin`.

### Help:
```sh
$ py --help
usage: py [-h] [--version] [-e] [-b] [-n] [-s] expr [expr ...]

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
  -s, --strict      Abort on the first row error instead of skipping the
                    row. Guarantees aggregates (xargs) never silently cover
                    partial data.
```
