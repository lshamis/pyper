# To run this test:
# $ pytest -vvv --cov=. ./tests.py

import os
import pty
import subprocess
import sys


def py_(
    args,
    in_=None,
    env=None,
    want_out=b"",
    want_err=b"",
    want_returncode=0,
    want_out_contains=None,
):
    stdin = subprocess.PIPE
    if in_ is None:
        stdin = pty.openpty()[1]
    else:
        in_ = "".join(line + "\n" for line in in_).encode()

    proc = subprocess.Popen(
        [sys.executable, "./pyper.py"] + args,
        stdin=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    out, err = proc.communicate(in_)
    if want_out_contains is not None:
        for fragment in want_out_contains:
            assert fragment in out
    else:
        assert out == want_out
    assert err == want_err
    assert proc.returncode == want_returncode


def skipped(n):
    return f"py: skipped {n} row(s) with errors; rerun with -e to see them.\n".encode()


def test_noarg():
    py_(
        [],
        want_err=b"""usage: py [-h] [-e] [-b] [-j JOBS] expr [expr ...]
py: error: the following arguments are required: expr
""",
        want_returncode=2,
    )


def test_help():
    # argparse phrasing drifts across Python versions ("optional arguments"
    # became "options"); check the stable fragments only.
    py_(
        ["-h"],
        want_out_contains=[
            b"usage: py [-h] [-e] [-b] [-j JOBS] expr [expr ...]",
            b"Expression to apply to all inputs.",
            b"--show-error",
            b"--show-bool",
        ],
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


def test_xargs_passes_errors_through():
    # Error rows must not be folded into the collected list.
    py_(
        ["int", "1 / x", "xargs", "len"],
        in_=["0", "4", "8"],
        want_out=b"2\n",
        want_err=skipped(1),
        want_returncode=1,
    )

    py_(
        ["-e", "int", "1 / x", "xargs", "len"],
        in_=["0", "4", "8"],
        want_out=b"2\n",
        want_err=b"py: row 0: ZeroDivisionError: division by zero\n",
        want_returncode=1,
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
        want_err=b"py: NameError: name 'b' is not defined\n",
        want_returncode=1,
    )


def test_unxargs():
    py_(
        ["5", "range", "unxargs"],
        want_out=b"0\n1\n2\n3\n4\n",
    )


def test_unxargs_flattens_every_row():
    # Regression: unxargs used to consume only the first row and silently
    # drop the rest of the stream.
    py_(
        ["split", "unxargs"],
        in_=["a b", "c d"],
        want_out=b"a\nb\nc\nd\n",
    )


def test_unxargs_passes_errors_through():
    # An error row must not stop later rows from being flattened.
    py_(
        ["int", "1 / x", "list(range(int(2 * x)))", "unxargs"],
        in_=["0", "1"],
        want_out=b"0\n1\n",
        want_err=skipped(1),
        want_returncode=1,
    )


def test_unxargs_string_is_atomic():
    # Strings are Iterable, but unxargs should not explode them into chars.
    py_(
        ["unxargs"],
        in_=["hello"],
        want_out=b"hello\n",
    )


def test_broken_pipe():
    # Downstream consumers closing early (e.g. `head`) must not traceback.
    proc = subprocess.run(
        "seq 100000 | ./pyper.py x | head -2",
        shell=True,
        capture_output=True,
    )
    assert proc.stdout == b"1\n2\n"
    assert b"Traceback" not in proc.stderr
    assert proc.returncode == 0


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
        want_err=skipped(1),
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


def test_assignment_delete_does_not_crash():
    # 'del a' removes a seeded symbol mid-expression; the row must not
    # turn into an error, and the old binding survives.
    py_(
        ["a=7", "del a", "a"],
        in_=["row"],
        want_out=b"7\n",
    )


def test_undefined_symbol():
    py_(
        ["foo"],
        want_err=skipped(1),
        want_returncode=1,
    )

    py_(
        ["-e", "foo"],
        want_err=b"py: NameError: name 'foo' is not defined\n",
        want_returncode=1,
    )

    py_(
        ["-e", "foo"],
        in_=["3", "4"],
        want_err=b"py: row 0: NameError: name 'foo' is not defined\n"
        b"py: row 1: NameError: name 'foo' is not defined\n",
        want_returncode=1,
    )


def test_undefined_attribute():
    py_(
        ["email.message.spacerace"],
        want_err=skipped(1),
        want_returncode=1,
    )


def test_attribute_error_on_value_does_not_crash():
    # Regression: a plain AttributeError (not the module-import pattern)
    # used to fail an assert inside the except handler and crash with a
    # traceback. It must behave like any other row error: filtered by
    # default, printed with -e.
    py_(
        ["x.fooo()"],
        in_=["hi"],
        want_err=skipped(1),
        want_returncode=1,
    )
    py_(
        ["-e", "x.fooo()"],
        in_=["hi"],
        want_err=b"py: row 0: AttributeError:"
        b" 'str' object has no attribute 'fooo'\n",
        want_returncode=1,
    )


def test_exception():
    py_(
        ["5 / 0"],
        want_err=skipped(1),
        want_returncode=1,
    )

    py_(
        ["-e", "5 / 0"],
        want_err=b"py: ZeroDivisionError: division by zero\n",
        want_returncode=1,
    )

    py_(
        ["int", "1 / x", "1 / x"],
        in_=["0", "4", "8"],
        want_out=b"4.0\n8.0\n",
        want_err=skipped(1),
        want_returncode=1,
    )

    py_(
        ["-e", "int", "1 / x", "1 / x"],
        in_=["0", "4", "8"],
        want_out=b"4.0\n8.0\n",
        want_err=b"py: row 0: ZeroDivisionError: division by zero\n",
        want_returncode=1,
    )


def test_jobs_preserves_order_and_semantics():
    rows = [str(n) for n in range(200)]
    expected = "".join(
        f"{n * 3}\n" for n in range(200) if (n * 3) % 2 == 1
    ).encode()
    for jobs_flags in ([], ["-j", "8"], ["-j8"], ["--jobs=8"]):
        py_(
            jobs_flags + ["int", "x * 3", "x % 2 == 1", "x"],
            in_=rows,
            want_out=expected,
        )


def test_jobs_with_errors_and_xargs():
    py_(
        ["-j", "4", "int", "1 / x", "xargs", "len"],
        in_=["0", "4", "8"],
        want_out=b"2\n",
        want_err=skipped(1),
        want_returncode=1,
    )


def test_jobs_io_bound_speedup():
    import time

    start = time.monotonic()
    py_(
        ["-j", "32", "time.sleep(0.05) or x"],
        in_=[str(n) for n in range(32)],
        want_out="".join(f"{n}\n" for n in range(32)).encode(),
    )
    # Serial would take >= 1.6s; allow generous slack for slow machines.
    assert time.monotonic() - start < 1.2


def test_jobs_bad_value():
    py_(
        ["-j", "0", "x"],
        want_err=b"usage: py [-h] [-e] [-b] [-j JOBS] expr [expr ...]\n"
        b"py: error: argument -j: invalid jobs value: '0'\n",
        want_returncode=2,
    )


def test_auto_import_does_not_double_evaluate(tmp_path):
    # Regression: auto-import used to work by catching NameError and
    # re-evaluating the expression, repeating any side effects that ran
    # before the failing name. Modules are now imported up front.
    marker = tmp_path / "marker"
    py_(
        [f'open("{marker}", "a").write("!") and wave.__name__'],
        in_=["row"],
        want_out=b"wave\n",
    )
    assert marker.read_text() == "!"


def test_user_symbols():
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".py") as file:
        print("__symbols__={'foo': 'bar'}", file=file, flush=True)

        py_(
            ["foo"],
            env={**os.environ, "PY_SYMBOL_FILEPATHS": file.name},
            want_out=b"bar\n",
        )
