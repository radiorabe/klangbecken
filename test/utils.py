import contextlib
import io
import sys


@contextlib.contextmanager
def capture(command, *args, **kwargs):
    out, sys.stdout = sys.stdout, io.StringIO()
    err, sys.stderr = sys.stderr, io.StringIO()
    commandException = None
    contextException = None
    ret = None
    try:
        try:
            ret = command(*args, **kwargs)
        except BaseException as e:
            # Catch any exception, store it for now, and first capture
            # all the output, before re-raising the exception.
            commandException = e
        sys.stdout.seek(0)
        sys.stderr.seek(0)
        out_data = sys.stdout.read()
        err_data = sys.stderr.read()
        sys.stdout = out
        sys.stderr = err
        try:
            yield out_data, err_data, ret
        except BaseException as e:
            # Catch any exception thrown from within the context manager
            # (often unittest assertions), and re-raise it later unmodified.
            contextException = e
    finally:
        # Do not ignore exceptions from within the context manager,
        # in case of a deliberately failing command.
        # Thus, prioritize contextException over commandException
        if contextException:
            raise contextException
        elif commandException:
            raise commandException
