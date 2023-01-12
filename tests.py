# To run this test:
# $ pytest -vvv --cov=. ./tests.py

import os
import pty
import subprocess


def py_(
    args,
    in_=None,
    env=None,
    want_out=b"",
    want_err=b"",
    want_returncode=0,
):
    stdin = subprocess.PIPE
    if in_ is None:
        stdin = pty.openpty()[1]
    else:
        in_ = "".join(line + "\n" for line in in_).encode()

    proc = subprocess.Popen(
        ["./py"] + args,
        stdin=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    out, err = proc.communicate(in_)
    assert out == want_out
    assert err == want_err
    assert proc.returncode == want_returncode


def test_noarg():
    py_(
        [],
        want_err=b"""usage: py [-h] [-e] [-b] expr [expr ...]
py: error: the following arguments are required: expr
""",
        want_returncode=2,
    )


def test_help():
    py_(
        ["-h"],
        want_out=b"""usage: py [-h] [-e] [-b] expr [expr ...]

positional arguments:
  expr              Expression to apply to all inputs.

optional arguments:
  -h, --help        show this help message and exit
  -e, --show-error  Print raised exceptions. Default is to skip.
  -b, --show-bool   Print bool values. Default is to use bool values as a
                    filter.
""",
    )


def test_simple():
    py_(
        ["5 + 5"],
        want_out=b"10\n",
    )


def test_single_pipe_input():
    py_(
        ["f'[[{x}]]'"],
        in_=["foo"],
        want_out=b"[[foo]]\n",
    )


def test_multiple_pipe_input():
    py_(
        ["f'[[{x}]]'"],
        in_=["foo", "bar"],
        want_out=b"[[foo]]\n[[bar]]\n",
    )


def test_multiple_pipe_expr():
    py_(
        ["int(x)", "x+5"],
        in_=["2"],
        want_out=b"7\n",
    )


def test_implicit_code_value():
    py_(
        ["int", "x+5"],
        in_=["2"],
        want_out=b"7\n",
    )


def test_generators():
    py_(
        ["int", "range", "sum"],
        in_=["5"],
        want_out=b"10\n",
    )


def test_xargs():
    py_(
        ["int", "xargs", "sorted"],
        in_=["5", "7", "3", "4"],
        want_out=b"[3, 4, 5, 7]\n",
    )


def test_xargs_empty():
    py_(
        ["xargs"],
        want_out=b"[]\n",
    )


def test_xargs_symbols():
    py_(
        ["-e", "a=0", "b=x", "1", "xargs", "a"],
        in_=["5", "7", "3", "4"],
        want_out=b"0\n",
    )

    py_(
        ["-e", "a=0", "b=x", "1", "xargs", "b"],
        in_=["5", "7", "3", "4"],
        want_out=b"name 'b' is not defined\n",
        want_returncode=1,
    )


def test_unxargs():
    py_(
        ["5", "range", "unxargs"],
        want_out=b"0\n1\n2\n3\n4\n",
    )


def test_unxargs_empty():
    py_(
        ["unxargs"],
    )

    py_(
        ["unxargs"],
        in_=[],
    )

    py_(
        ["5 / 0", "unxargs"],
        want_returncode=1,
    )


def test_none_passthrough():
    py_(
        ["int", "xargs", "sort"],
        in_=["5", "7", "3", "4"],
        want_out=b"[3, 4, 5, 7]\n",
    )


def test_bool_filter():
    py_(
        ["int", "x > 4"],
        in_=["5", "7", "3", "4"],
        want_out=b"5\n7\n",
    )
    py_(
        ["-b", "int", "x > 4"],
        in_=["5", "7", "3", "4"],
        want_out=b"True\nTrue\nFalse\nFalse\n",
    )


def test_auto_import():
    py_(
        ["json.loads", "x['a']"],
        in_=['{"a":3}'],
        want_out=b"3\n",
    )


def test_auto_import_submodule():
    py_(
        [
            "email.message.Message()",
            'x.set_param("key", "val")',
            'x.set_payload("content")',
            "x.as_string()",
        ],
        want_out=b'Content-Type: text/plain; key="val"\n\ncontent\n',
    )


def test_assignment():
    py_(
        ["int", "k=1000", "x*k"],
        in_=["9"],
        want_out=b"9000\n",
    )


def test_assignment_overwrite():
    py_(
        ["int", "a=x", "a*x", "a=x", "a"],
        in_=["3"],
        want_out=b"9\n",
    )


def test_undefined_symbol():
    py_(
        ["foo"],
        want_returncode=1,
    )

    py_(
        ["-e", "foo"],
        want_out=b"name 'foo' is not defined\n",
        want_returncode=1,
    )

    py_(
        ["-e", "foo"],
        in_=["3", "4"],
        want_out=b"name 'foo' is not defined\nname 'foo' is not defined\n",
        want_returncode=1,
    )


def test_undefined_attribute():
    py_(
        ["email.message.spacerace"],
        want_returncode=1,
    )


def test_exception():
    py_(
        ["5 / 0"],
        want_returncode=1,
    )

    py_(
        ["-e", "5 / 0"],
        want_out=b"division by zero\n",
        want_returncode=1,
    )

    py_(
        ["int", "1 / x", "1 / x"],
        in_=["0", "4", "8"],
        want_out=b"4.0\n8.0\n",
        want_returncode=1,
    )

    py_(
        ["-e", "int", "1 / x", "1 / x"],
        in_=["0", "4", "8"],
        want_out=b"division by zero\n4.0\n8.0\n",
        want_returncode=1,
    )


def test_user_symbols():
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".py") as file:
        print("__symbols__={'foo': 'bar'}", file=file, flush=True)

        py_(
            ["foo"],
            env={**os.environ, "PY_SYMBOL_FILEPATHS": file.name},
            want_out=b"bar\n",
        )
