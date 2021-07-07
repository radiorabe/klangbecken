import collections
import csv
import datetime
import json
import os
import shlex
import subprocess
import sys
import uuid

import docopt
from werkzeug.exceptions import UnprocessableEntity

from .api import development_server
from .playlist import (
    DEFAULT_PROCESSORS,
    DEFAULT_UPLOAD_ANALYZERS,
    FileAddition,
    MetadataChange,
    check_processor,
    ffmpeg_audio_analyzer,
    locked_open,
)
from .settings import (
    ALLOWED_METADATA,
    LOG_KEYS,
    PLAYLISTS,
    SUPPORTED_FILE_TYPES,
    TAG_KEYS,
)


def _check_data_dir(data_dir, create=False):
    """Create local data directory structure for testing and development."""
    for path in [data_dir, os.path.join(data_dir, "log")] + [
        os.path.join(data_dir, playlist) for playlist in PLAYLISTS
    ]:
        if not os.path.isdir(path):
            if create:
                os.mkdir(path)
            else:
                raise Exception(f"Directory '{path}' does not exist")
    for path in [os.path.join(data_dir, d + ".m3u") for d in PLAYLISTS]:
        if not os.path.isfile(path):
            if create:
                with open(path, "a"):
                    pass
            else:
                raise Exception(f"Playlist '{path}'' does not exist")
    path = os.path.join(data_dir, "index.json")
    if not os.path.isfile(path):
        if create:
            with open(path, "w") as f:
                f.write("{}")
        else:
            raise Exception('File "index.json" does not exist')


def init_cmd(data_dir):
    """Entry point for `init` command.

    Initialize data directory structure.
    """
    if os.path.exists(data_dir):
        if os.path.isdir(data_dir) and len(os.listdir(data_dir)) != 0:
            print(
                f"ERROR: Data directory {data_dir} exists but is not empty.",
                file=sys.stderr,
            )
            exit(1)
    else:
        os.mkdir(data_dir)
    _check_data_dir(data_dir, create=True)


def serve_cmd(address, port, data_dir, player_socket):  # pragma: no cover
    """Entry point for `serve` command.

    Run a local stand-alone server for development.
    """
    from werkzeug.serving import run_simple

    app = development_server(data_dir, player_socket)

    run_simple(address, port, app, threaded=True, use_reloader=True, use_debugger=True)


def import_cmd(  # noqa: C901
    data_dir, playlist, files, yes, meta=None, use_mtime=False
):
    """Entry point for `import` command."""

    def err(*args):
        print(*args, file=sys.stderr)

    try:
        _check_data_dir(data_dir)
    except Exception as e:  # pragma: no cover
        err("ERROR: Problem with data directory.", str(e))
        sys.exit(1)

    if playlist not in PLAYLISTS:
        err("ERROR: Invalid playlist name: {playlist}")
        sys.exit(1)

    if meta:
        with open(meta) as f:
            metadata = json.load(f)
    else:
        metadata = {}

    analysis_data = []
    for filename in files:
        try:
            if filename in metadata or not meta:
                song_data = _analyze_one_file(data_dir, playlist, filename, use_mtime)
                if filename in metadata:
                    song_data[3].extend(
                        MetadataChange(key, metadata[filename][key])
                        for key in "artist title".split()
                    )
                analysis_data.append(song_data)
            else:
                print("Ignoring", filename)

        except UnprocessableEntity as e:
            err("WARNING: File cannot be analyzed: " + filename)
            err("WARNING: " + e.description if hasattr(e, "description") else str(e))
        except Exception as e:  # pragma: no cover
            err("WARNING: Unknown error when analyzing file: " + filename)
            err("WARNING: " + e.description if hasattr(e, "description") else str(e))

    print(f"Successfully analyzed {len(analysis_data)} of {len(files)} files.")
    count = 0
    if yes or input("Start import now? [y/N] ").strip().lower() == "y":
        for filename, fileId, ext, actions in analysis_data:
            try:
                for processor in DEFAULT_PROCESSORS:
                    processor(data_dir, playlist, fileId, ext, actions)
                count += 1
            except Exception as e:  # pragma: no cover
                err(
                    "WARNING: File cannot be imported: " + filename,
                    e.description if hasattr(e, "description") else str(e),
                )

    print(f"Successfully imported {count} of {len(files)} files.")
    sys.exit(1 if count < len(files) else 0)


def _analyze_one_file(data_dir, playlist, filename, use_mtime):
    """Helper for import command: Analyze a single audio file."""

    if not os.path.exists(filename):
        raise UnprocessableEntity("File not found: " + filename)

    ext = os.path.splitext(filename)[1].lower()[1:]
    if ext not in SUPPORTED_FILE_TYPES.keys():
        raise UnprocessableEntity("File extension not supported: " + ext)

    with open(filename, "rb") as importFile:
        fileId = str(uuid.uuid4())
        actions = []
        for analyzer in DEFAULT_UPLOAD_ANALYZERS:
            actions += analyzer(playlist, fileId, ext, importFile)

        actions.append(MetadataChange("original_filename", os.path.basename(filename)))

        if use_mtime:
            mtime = os.stat(filename).st_mtime
            mtime = datetime.datetime.fromtimestamp(mtime)
            mtime = mtime.isoformat()
            actions.append(MetadataChange("import_timestamp", mtime))

        actions[0] = FileAddition(filename)
    return (filename, fileId, ext, actions)


def fsck_cmd(data_dir):  # noqa: C901
    """Entry point for `fsck` command."""

    song_id = None

    def err(*args):
        if song_id is not None:
            print("ERROR when processing", song_id, file=sys.stderr)
        print(*args, file=sys.stderr)
        err.count += 1

    err.count = 0

    try:
        _check_data_dir(data_dir)
    except Exception as e:
        err("ERROR: Problem with data directory.", str(e))
        sys.exit(1)

    with locked_open(os.path.join(data_dir, "index.json")) as f:
        try:
            data = json.load(f)
        except ValueError as e:
            err("ERROR: Cannot read index.json", str(e))
            sys.exit(1)  # abort

        files = set()
        playlist_counts = collections.Counter()
        for playlist in PLAYLISTS:
            files.update(
                os.path.join(playlist, entry)
                for entry in os.listdir(os.path.join(data_dir, playlist))
            )
            with open(os.path.join(data_dir, playlist + ".m3u")) as f1:
                playlist_counts.update(line.strip() for line in f1.readlines())
        for song_id, entries in data.items():
            keys = set(entries.keys())
            missing = set(ALLOWED_METADATA.keys()) - keys
            if missing:
                err("ERROR: missing entries:", ", ".join(missing))
                continue  # cannot continue with missing entries
            too_many = keys - set(ALLOWED_METADATA.keys())
            if too_many:
                err("ERROR: too many entries:", ", ".join(too_many))
            try:
                check_processor(
                    data_dir,
                    entries["playlist"],
                    entries["id"],
                    entries["ext"],
                    (MetadataChange(key, val) for key, val in entries.items()),
                )
            except UnprocessableEntity as e:
                err("ERROR:", str(e))
            if song_id != entries["id"]:
                err("ERROR: Id missmatch", song_id, entries["id"])
            if entries["cue_in"] > 10:
                err("WARNING: cue_in after more than ten seconds:", entries["cue_in"])
            if entries["cue_out"] < entries["length"] - 10:
                err(
                    "WARNING: cue_out earlier than ten seconds before end of song:",
                    entries["cue_out"],
                )
            if entries["cue_in"] > entries["cue_out"]:
                err(
                    "ERROR: cue_in larger than cue_out",
                    str(entries["cue_in"]),
                    str(entries["cue_out"]),
                )
            # Tolerate small differences, as the length calculation is not
            # perfectly accurate.
            if entries["cue_out"] > entries["length"] + 0.1:
                err(
                    "ERROR: cue_out larger than length",
                    str(entries["cue_out"]),
                    str(entries["length"]),
                )
            if entries["playlist"] != "jingles" and entries["length"] < 30:
                err("WARNING: very short song found:", entries["length"])
            file_path = os.path.join(
                entries["playlist"], entries["id"] + "." + entries["ext"]
            )
            file_full_path = os.path.join(data_dir, file_path)
            if not os.path.isfile(file_full_path):
                err("ERROR: file does not exist:", file_full_path)
            else:
                files.remove(file_path)
                FileType = SUPPORTED_FILE_TYPES[entries["ext"]]
                mutagenfile = FileType(file_full_path)
                for key in TAG_KEYS:
                    tag_value = mutagenfile.get(key, [""])[0]
                    if str(entries[key]) != tag_value:
                        err(
                            f"ERROR: Tag value mismatch '{key}': "
                            f"{entries[key]} != {tag_value}"
                        )

                count = playlist_counts[file_path]
                del playlist_counts[file_path]
                if count != entries["weight"]:
                    err(
                        f"ERROR: Playlist weight mismatch: "
                        f"{entries['weight']} != {count}"
                    )

        if files:
            err("ERROR: Dangling files:", ", ".join(files))
        if playlist_counts:
            err("ERROR: Dangling playlist entry:", ", ".join(playlist_counts.keys()))

    sys.exit(1 if err.count else 0)


def playlog_cmd(data_dir, filename):
    """Entry point for `playlog` command.

    Log track play in metadata, log files, and with external command.
    """
    file_id, ext = filename.split("/")[-1].split(".")
    now = datetime.datetime.now().astimezone()

    # Update metadata (play_count and last_play)
    with locked_open(os.path.join(data_dir, "index.json")) as f:
        data = json.load(f)
        entry = data[file_id]
        play_count = entry.get("play_count", 0) + 1

    changes = [
        MetadataChange("play_count", play_count),
        MetadataChange("last_play", now.isoformat()),
        MetadataChange("last_play_epoch", now.timestamp()),
    ]

    for processor in DEFAULT_PROCESSORS:
        processor(data_dir, entry["playlist"], file_id, ext, changes)

    entry.update(changes)

    # Append to CSV log files
    log_file_name = f"{now.year}-{now.month:02d}.csv"
    log_file_path = os.path.join(data_dir, "log", log_file_name)

    if not os.path.exists(log_file_path):
        # Initialize file for new month
        with open(log_file_path, "w", encoding="utf-8", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=LOG_KEYS)
            writer.writeheader()

    with open(log_file_path, "a", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=LOG_KEYS)
        writer.writerow({key: val for key, val in entry.items() if key in LOG_KEYS})

    if EXTERNAL_PLAY_LOGGER:
        # Quote inserted field values to prevent shell injections
        quoted_entry = {key: shlex.quote(str(value)) for key, value in entry.items()}
        cmd = shlex.split(EXTERNAL_PLAY_LOGGER.format(**quoted_entry))
        # Force UTF-8 encoding
        subprocess.check_call([arg.encode("utf-8") for arg in cmd])


EXTERNAL_PLAY_LOGGER = os.environ.get("KLANGBECKEN_EXTERNAL_PLAY_LOGGER", "")


def reanalyze_cmd(data_dir, ids, all, yes):
    """Entry point for `reanalyze` command.

    Re-run audio analyzer for selected files and update gain values and cue points.
    """
    with locked_open(os.path.join(data_dir, "index.json")) as f:
        data = json.load(f)
    if all:
        ids = data.keys()

    changes = []
    for id in ids:
        playlist = data[id]["playlist"]
        ext = data[id]["ext"]
        path = os.path.join(data_dir, playlist, id + "." + ext)
        print(f'File: {path} ({data[id]["artist"]} - {data[id]["title"]})')
        with open(path) as f:
            file_changes = ffmpeg_audio_analyzer(playlist, id, ext, f)
        changes.append((playlist, id, ext, file_changes))
        for key, val in file_changes:
            print(f" * {key}: {val}")

    if yes or input("Apply changes now? [y/N] ").strip().lower() == "y":
        for playlist, id, ext, file_changes in changes:
            for processor in DEFAULT_PROCESSORS:
                processor(data_dir, playlist, id, ext, file_changes)


def main():
    """Klangbecken audio playout system.

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
            Read metadata from JSON file. Files without entries are skipped.
      --all
            Reanalyze all files.
    """
    from . import __version__

    args = docopt.docopt(main.__doc__, version=f"Klangbecken {__version__}")

    data_dir = args["--data"]

    if os.path.exists(data_dir) and not os.path.isdir(data_dir):
        print(
            f"ERROR: Data directory '{data_dir}' exists, but is not a directory.",
            file=sys.stderr,
        )
        exit(1)

    if not os.path.isdir(data_dir) and not args["init"]:
        print(f"ERROR: Data directory '{data_dir}' does not exist.", file=sys.stderr)
        exit(1)

    if args["init"]:
        init_cmd(data_dir)
    elif args["serve"]:  # pragma: no cover
        serve_cmd(args["--bind"], int(args["--port"]), data_dir, args["--socket"])
    elif args["import"]:
        import_cmd(
            data_dir,
            args["PLAYLIST"],
            args["FILE"],
            yes=args["--yes"],
            meta=args["--meta"],
            use_mtime=args["--mtime"],
        )
    elif args["fsck"]:
        fsck_cmd(data_dir)
    elif args["playlog"]:
        playlog_cmd(data_dir, args["FILE"][0])
    elif args["reanalyze"]:
        reanalyze_cmd(data_dir, args["ID"], args["--all"], args["--yes"])
