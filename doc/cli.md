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

### `init`

Initialize the data directory by creating empty playlist files, playlist folders and other default files.

### `serve`

Run the development server. Serves the API from `/api` and the static files from the data directory from `/data`.

### `import`

Batch import audio files to the specified playlist.  Artist and title metadata can be supplied from a JSON file mapping filenames to a metadata dict. E.g.
```json
{
    "importfolder/xyz.mp3": {"artist": "Hansi Hinterseher", "title": "A Bussarl"}
    ...
}
```

### `fsck`

Validate the correctness of the `index.json` metadata cache.

### `playlog`

Log the airing of a track. This command is called from the liquidsoap player. It updates the `last_play` and `play_count` metadata, appends the data to the monthly playlog in `data/log/`, and calls the external play logger if configured.

### `reanalyze`

Re-run the audio analyzer for the specified files.
