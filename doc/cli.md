# Command Line Interface

The command line tool can be called with Python `python -m klangbecken` or as a stand-alone command `klangbecken` when the package is installed.

```
Klangbecken audio playout system.

Usage:
    klangbecken (--help | --version)
    klangbecken init [-d DATA_DIR]
    klangbecken serve [-d DATA_DIR] [-p PORT] [-b ADDRESS] [-s PLAYER_SOCKET]
    klangbecken import [-d DATA_DIR] [-y] [-m] [-M FILE] PLAYLIST FILE...
    klangbecken fsck [-d DATA_DIR]
    klangbecken playlog [-d DATA_DIR] FILE
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
    -s PLAYER_SOCKET, --socket=PLAYER_SOCKET
        Set the location or address of the liquisoap player socket.
        This can either be the path to a UNIX domain socket file or
        a domain name and port seperated by a colon (e.g. localhost:123)
        [default: ./klangbecken.sock]
    -y, --yes
        Automatically answer yes to all questions.
    -m, --mtime
        Use file modification date as import timestamp.
    -M FILE, --meta=FILE
        Read metadata from JSON file.  Files without entries are skipped.
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
    "importfolder/xyz.mp3": {"artist": "Wildecker Herzbuam", "title": "Herzilein"},
    "..."
}
```
Files that have no entry in the metadata file are skipped.

### `fsck`

Validate the `index.json` metadata cache integrity.

### `playlog`

Log the airing of a track. This command is called from the liquidsoap player. It updates the `last_play`, `last_play_epoch` and `play_count` metadata, appends the data to the monthly playlog in `data/log/`, and calls the external play logger if configured.

The `last_play` is stored in the ISO8601 date format. To simplify the liquidsoap player code, the `last_play` date is stored in the audio file tag `last_play_epoch` as a UNIX epoch date.

If the environment variable `KLANGBECKEN_EXTERNAL_PLAY_LOGGER` is set, it will be used to call an external play logger. This can be used publish the information for example in a song ticker on a public web site. The command will be interpreted as a formatting string. All supported metadata keys are available (see [settings.py](../klangbecken/settings.py)).

Example:
```bash
KLANGBECKEN_EXTERNAL_PLAY_LOGGER="/usr/local/bin/myscript.sh {playlist} {id} {artist} {title}
```

### `reanalyze`

Re-run the audio analyzer for the specified files.
