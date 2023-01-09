# Python pipe helper:
The `py` script makes bash hacking easier by allowing python expressions to be intermixed.

`py` takes expression arguments that will be executed on all piped strings.

For example, you can help get pids for Xorg processes:
```sh
$ ps aux | grep Xorg | py 'x.split()[1]'
24723
24992
```

You can also chain multiple operations by providing multiple expressions:
```sh
$ ps aux | grep Xorg | py 'x.split()' 'x[1]'
24723
24992
```

For simple commands, where the evaluation if of the form `expr(value)` or `value(expr)`, you don't need to be explicit with the call. For example:
```sh
$ ps aux | grep Xorg | py split 'x[1]'
24723
24992
```

You can convert from operating on one input at a time, to operating on the collection of inputs by using `xargs`:
```sh
$ ps aux | py split 'x[0]' xargs collections.Counter
Counter({'root': 254, 'lshamis': 187, 'dbus': 2, 'td-agent': 2, 'avahi': 2, 'USER': 1, 'polkitd': 1, 'rtkit': 1, 'chrony': 1, 'colord': 1, 'nobody': 1, 'dnsmasq': 1, 'systemd+': 1})
```

And you can undo the process, converting a single collection to indepent inputs using `unxargs`:
```sh
$ ls py | py open readlines unxargs rstrip '"sys" in x'
import sys
        public_modules = {k: v for k, v in sys.modules.items() if not k.startswith("_")}
        while not name or name in sys.modules:
    if sys.stdin.isatty():
    for i, x in enumerate(sys.stdin):
    sys.exit(main())
```

In the above example we used the boolean expression `'"sys" in x'` as a filter.
Boolean expressions act as filters unless `--show-bool` is included:
```sh
$ ls / | py 'len(x) > 3'
boot
home
lib64
media
proc
root
sbin

$ ls / | py -b 'len(x) > 3'
False
False
True
False
False
True
False
True
True
False
False
True
True
False
True
False
True
False
```

### Installation:
Copy the `py` file into any place in your PATH.

Optionally copy the `extra_symbols.py` file into `~/.config/py/extra_symbols.py`. Doing so will first class symbols in common modules, prefixed by an `_`. For example:
```sh
$ py _digits
0123456789
$ py _random
0.48314627566684964
$ py _pi
3.141592653589793
$ ls | py _abspath
/home/lshamis/github/lshamis/pyper/extra_symbols.py
/home/lshamis/github/lshamis/pyper/py
/home/lshamis/github/lshamis/pyper/README.md
$ echo 'Hello, World!' | py '_shorten(x, width=12)'
Hello, [...]
$ echo 'Hello, World!' | py '_wrap(x, width=12)' -t unxargs
Hello,
World!
```

### Help:
```sh
$ py --help
usage: py [-h] [-e] [-b] [-n] expr [expr ...]

positional arguments:
  expr              Expression to apply to all inputs.

options:
  -h, --help        show this help message and exit
  -e, --show-error  Print raised exceptions. Default is to skip.
  -b, --show-bool   Print bool values. Default is to use bool values as a filter.
  -n, --show-none   Print None values. Default is to use None as a filter.
```
