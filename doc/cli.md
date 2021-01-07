# Command Line Interface

The command line tool can be called directly from the source code `python klangbecken.py` or as command `klangbecken` when the package is installed.

```
Klangbecken audio playout system.

Usage:
    klangbecken (--help | --version)
    klangbecken init [-d DATA_DIR]
    klangbecken serve [-d DATA_DIR] [-p PORT] [-b ADDRESS]
    klangbecken import [-d DATA_DIR] [-y] [-m] [-M FILE] PLAYLIST FILE...
    klangbecken fsck [-d DATA_DIR] [-R]
    klangbecken playlog [-d DATA_DIR] (--off | FILE)
    klangbecken reanalyze [-d DATA_DIR] [-y] (--all | ID...)

Options:
    -h, --help
        Show this help message and exit.
    --version
        Show version and exit.
    -d DIR, --data=DIR
        Set data directory location [default: ./data/].
    -p PORT, --port=PORT
        Specify alternate port [default: 5000].
    -b ADDRESS, --bind=ADDRESS
        Specify alternate bind address [default: localhost].
    -y, --yes
        Automatically answer yes to all questions.
    -m, --mtime
        Use file modification date as import timestamp.
    -M FILE, --meta=FILE
        Read metadata from JSON file. Missing entries will be skipped.
    -R, --repair
        Try to repair index.
    --off
        Take klangbecken off the air.
    --all
        Reanalyze all files.
```
