import collections
import csv
import datetime
import json
import os
import subprocess
import sys
import uuid

from werkzeug.exceptions import UnprocessableEntity

from .api import StandaloneWebApplication
from .playlist import (
    DEFAULT_PROCESSORS,
    DEFAULT_UPLOAD_ANALYZERS,
    FileAddition,
    MetadataChange,
    check_processor,
    ffmpeg_audio_analyzer,
    locked_open,
)
from .settings import ALLOWED_METADATA, PLAYLISTS, SUPPORTED_FILE_TYPES, TAG_KEYS
from .utils import _check_data_dir


def init_cmd(data_dir):
    if os.path.exists(data_dir):
        if os.path.isdir(data_dir) and len(os.listdir(data_dir)) != 0:
            print(f"ERROR: Data directory {data_dir} exists but is not empty.")
            exit(1)
    else:
        os.mkdir(data_dir)
    _check_data_dir(data_dir, create=True)


def serve_cmd(data_dir, address="localhost", port=5000, dev_mode=False):
    # Run locally in stand-alone development mode
    from werkzeug.serving import run_simple

    app = StandaloneWebApplication(data_dir, "no secret")

    run_simple(
        address, port, app, threaded=True, use_reloader=dev_mode, use_debugger=dev_mode
    )


def import_cmd(  # noqa: C901
    data_dir, playlist, files, yes, meta=None, use_mtime=True, dev_mode=False
):
    """Entry point for import script."""

    def err(*args):
        print(*args, file=sys.stderr)

    try:
        _check_data_dir(data_dir)
    except Exception as e:
        err("ERROR: Problem with data directory.", str(e))
        sys.exit(1)

    if playlist not in PLAYLISTS:
        err("ERROR: Invalid playlist name: {playlist}")
        sys.exit(1)

    if meta:
        metadata = json.load(open(meta))
    else:
        metadata = {}

    analysis_data = []
    for filename in files:
        try:
            if filename in metadata or not meta:
                song_data = _analyze_one_file(data_dir, playlist, filename)

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


def _analyze_one_file(data_dir, playlist, filename, use_mtime=True):
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


def fsck_cmd(data_dir, repair=False, dev_mode=False):  # noqa: C901
    """Entry point for fsck script."""

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
                    "WARNING: cue_out earlier than ten seconds before end of " "song:",
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


def playlog_cmd(data_dir, filename, off_air=False, dev_mode=False):
    if off_air:
        with open(os.path.join(data_dir, "log", "current.json"), "w") as f:
            json.dump(False, f)
        return

    file_id, ext = filename.split("/")[-1].split(".")

    json_opts = {"indent": 2, "sort_keys": True} if dev_mode else {}

    now = datetime.datetime.now()

    # Update index cache
    with locked_open(os.path.join(data_dir, "index.json")) as f:
        data = json.load(f)
        entry = data[file_id]
        entry["play_count"] = entry.get("play_count", 0) + 1
        entry["last_play"] = now.isoformat()
        f.seek(0)
        f.truncate()
        json.dump(data, f, **json_opts)
        del data

    # Update file metadata
    FileType = SUPPORTED_FILE_TYPES[ext]
    mutagenfile = FileType(filename)
    mutagenfile["last_play"] = str(now.timestamp())
    mutagenfile.save()

    # Overwrite current.json
    with open(os.path.join(data_dir, "log", "current.json"), "w") as f:
        json.dump(entry, f, **json_opts)

    # Append to CSV log files
    log_file_name = f"{now.year}-{now.month}.csv"
    log_file_path = os.path.join(data_dir, "log", log_file_name)

    if not os.path.exists(log_file_path):
        with open(log_file_path, "w", encoding="utf-8", newline="") as csv_file:
            fieldnames = ALLOWED_METADATA.keys()
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
            writer.writeheader()

    with open(log_file_path, "a", encoding="utf-8", newline="") as csv_file:
        fieldnames = ALLOWED_METADATA.keys()
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writerow(entry)

    if EXTERNAL_PLAY_LOGGER:
        subprocess.check_call(
            EXTERNAL_PLAY_LOGGER.format(**entry).encode("utf-8"), shell=True
        )


EXTERNAL_PLAY_LOGGER = os.environ.get("KLANGBECKEN_EXTERNAL_PLAY_LOGGER", "")


def reanalyze_cmd(data_dir, ids, all=False, yes=False, dev_mode=False):
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


def main(dev_mode=False):
    """Klangbecken audio playout system.

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
    """
    from docopt import docopt

    from . import __version__

    args = docopt(main.__doc__, version=f"Klangbecken {__version__}")

    data_dir = args["--data"]

    if os.path.exists(data_dir) and not os.path.isdir(data_dir):
        print(
            f"ERROR: Data directory '{data_dir}' exists, but is not a " "directory.",
            file=sys.stderr,
        )
        exit(1)

    if not os.path.isdir(data_dir) and not args["init"]:
        print(f"ERROR: Data directory '{data_dir}' does not exist.", file=sys.stderr)
        exit(1)

    if args["init"]:
        init_cmd(data_dir)
    elif args["serve"]:
        serve_cmd(
            data_dir,
            address=args["--bind"],
            port=int(args["--port"]),
            dev_mode=dev_mode,
        )
    elif args["import"]:
        import_cmd(
            data_dir,
            args["PLAYLIST"],
            args["FILE"],
            yes=args["--yes"],
            meta=args["--meta"],
            use_mtime=args["--mtime"],
            dev_mode=dev_mode,
        )
    elif args["fsck"]:
        fsck_cmd(data_dir, repair=args["--repair"], dev_mode=dev_mode)
    elif args["playlog"]:
        if args["--off"]:
            playlog_cmd(data_dir, "", args["--off"], dev_mode=dev_mode)
        else:
            playlog_cmd(data_dir, args["FILE"][0], dev_mode=dev_mode)
    elif args["reanalyze"]:
        reanalyze_cmd(
            data_dir, args["ID"], args["--all"], args["--yes"], dev_mode=dev_mode
        )
