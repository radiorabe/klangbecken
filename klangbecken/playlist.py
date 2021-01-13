import collections
import contextlib
import datetime
import fcntl
import json
import os
import re
import shutil
import subprocess
import threading

import mutagen
import mutagen.easyid3
import mutagen.flac
import mutagen.mp3
import mutagen.oggvorbis
from werkzeug.exceptions import NotFound, UnprocessableEntity

from .settings import ALLOWED_METADATA, SUPPORTED_FILE_TYPES, TAG_KEYS, UPDATE_KEYS

####################
# Change-"Classes" #
####################
FileAddition = collections.namedtuple("FileAddition", ("file"))
MetadataChange = collections.namedtuple("MetadataChange", ("key", "value"))
FileDeletion = collections.namedtuple("FileDeletion", ())


#############
# Analyzers #
#############
def raw_file_analyzer(playlist, fileId, ext, file_):
    """Initial analysis of the file.

    Set the import timestamp, and default values for various metadata fields.
    """
    if not file_:
        raise UnprocessableEntity("No File found")

    if ext not in SUPPORTED_FILE_TYPES.keys():
        raise UnprocessableEntity(f"Unsupported file extension: {ext}")

    # Be compatible with werkzeug.datastructures.FileStorage and plain files
    filename = file_.filename if hasattr(file_, "filename") else file_.name

    now = datetime.datetime.now().astimezone()

    return [
        FileAddition(file_),
        MetadataChange("id", fileId),
        MetadataChange("ext", ext),
        MetadataChange("playlist", playlist),
        MetadataChange("original_filename", filename),
        MetadataChange("import_timestamp", now.isoformat()),
        MetadataChange("weight", 1),
        MetadataChange("play_count", 0),
        MetadataChange("last_play", ""),
        MetadataChange("last_play_epoch", 0.0),
    ]


def mutagen_tag_analyzer(playlist, fileId, ext, file_):
    """Extract tag information from the file.

    Artist name, track title, album title and track length are extracted.
    """
    with _mutagenLock:
        MutagenFileType = SUPPORTED_FILE_TYPES[ext]
        try:
            mutagenfile = MutagenFileType(file_)
        except mutagen.MutagenError:
            raise UnprocessableEntity(
                "Unsupported file type: " + "Cannot read metadata."
            )
        changes = [
            MetadataChange("artist", mutagenfile.get("artist", [""])[0]),
            MetadataChange("title", mutagenfile.get("title", [""])[0]),
            MetadataChange("album", mutagenfile.get("album", [""])[0]),
            MetadataChange("length", mutagenfile.info.length),
        ]
    # Seek back to the start of the file for whoever comes next
    file_.seek(0)
    return changes


silence_re = re.compile(r"silencedetect.*silence_(start|end):\s*(\S*)")
trackgain_re = re.compile(r"replaygain.*track_gain = (\S* dB)")


def ffmpeg_audio_analyzer(playlist, fileId, ext, file_):
    """Analyze the audio data with ffmpeg.

    This function does two things:
    - Calculate the replaygain value for loudness normalization.
    - Detect silence periods at the start and end of the track, and
      calculate the according cue points.
    """
    # To make sure that we find the correct cue_out point, we append ~0.2 seconds
    # of silence to the end of the track (with the `apad=pad_len=10000` option).
    # This guarantees that we always find at least one silence period.
    #
    # Also, we have no a priori knowledge of the exact length of the track, to which
    # we could fall back to. Whereas at the start of the track it is easy: we can
    # always fall back to 0.0.
    command = """ffmpeg -i - -af
    replaygain,apad=pad_len=10000,silencedetect=d=0.01 -f null -""".split()

    try:
        raw_output = subprocess.check_output(
            command, stdin=file_, stderr=subprocess.STDOUT
        )
        # Non-ASCII characters can safely be ignored
        output = str(raw_output, "ascii", errors="ignore")
    except subprocess.CalledProcessError:
        raise UnprocessableEntity("Cannot process audio data")

    # Extract ReplayGain value
    gain = trackgain_re.search(output).groups()[0]

    # Extract silence periods
    silence_times = re.findall(silence_re, output)

    # Start times of silence periods (there is at least one value)
    start_times = [float(value) for name, value in silence_times if name == "start"]

    # End times for the silence periods (might be empty)
    end_times = [float(value) for name, value in silence_times if name == "end"]

    # Cue in a the end of first silence period, if the track starts with silence
    if start_times[0] < 0.05:
        # First silence period begins at the beginning of the track

        # Fix negative values from old ffmpeg versions:
        # End_times might be empty for silence only tracks (and old ffmpeg versions)
        # Also, old versions of ffmpeg return small negative values (-0.01) instead
        # of 0.0
        cue_in = max(end_times[:1] + [0.0])
    else:
        # First silence period begins somewehere in the middle of the track
        # Cue in at the start of the track
        cue_in = 0.0

    # Cue out at the start of the last silence period.
    # Fix small negative values (for old ffmpeg versions)
    cue_out = max(start_times[-1], 0.0)

    # Empty or almost empty track (there should be more than 0.5 seconds of audio)
    if cue_in >= cue_out - 0.5:
        # Nothing but silence found
        raise UnprocessableEntity("The track only contains silence: Check your file.")

    if cue_in > 10:
        # Fail for unusually large cue_in values:
        # This will generate an error when uploading, and thus make it easier to sort
        # out bogus audio tracks, or catch clearly wrong audio file analysis results.
        raise UnprocessableEntity(
            f"Too much silence ({cue_in}s) found at the start of the track: "
            f"Check your file."
        )

    file_.seek(0)
    return [
        MetadataChange("track_gain", gain),
        MetadataChange("cue_in", cue_in),
        MetadataChange("cue_out", cue_out),
    ]


DEFAULT_UPLOAD_ANALYZERS = [
    raw_file_analyzer,
    mutagen_tag_analyzer,
    ffmpeg_audio_analyzer,
]


def update_data_analyzer(playlist, fileId, ext, data):
    """Prevent updating illegal fields."""
    changes = []
    if not isinstance(data, dict):
        raise UnprocessableEntity("Invalid data format: associative array expected")
    for key, value in data.items():
        if key not in UPDATE_KEYS:
            raise UnprocessableEntity(f"Invalid data format: Key not allowed: {key}")
        changes.append(MetadataChange(key, value))
    return changes


DEFAULT_UPDATE_ANALYZERS = [update_data_analyzer]


##############
# Processors #
##############
def check_processor(data_dir, playlist, fileId, ext, changes):
    """Validate metadata changes.

    Enforce type and contract checks.
    """
    for change in changes:
        if isinstance(change, MetadataChange):
            key, val = change

            if key not in ALLOWED_METADATA.keys():
                raise UnprocessableEntity(f"Invalid metadata key: {key}")

            checks = ALLOWED_METADATA[key]
            if not isinstance(checks, (list, tuple)):
                checks = (checks,)

            for check in checks:
                _check_value(key, val, check)

        elif isinstance(change, (FileAddition, FileDeletion)):
            pass
        else:
            raise ValueError("Invalid change class")


def _check_value(key, val, check):
    if isinstance(check, type):
        if not isinstance(val, check):
            raise UnprocessableEntity(
                f"Invalid data format for '{key}': Type error "
                f"(expected {check.__name__}, got {type(val).__name__})."
            )
    elif callable(check):
        if not check(val):
            raise UnprocessableEntity(
                f'Invalid data format for "{key}": Check failed (value: "{val}").'
            )
    elif isinstance(check, str):
        if re.match(check, val) is None:
            raise UnprocessableEntity(
                f"Invalid data format for '{key}': Regex check failed (value: '{val}'"
                f", regex: '{check}'')."
            )
    else:
        raise NotImplementedError()  # pragma: no cover


def filter_duplicates_processor(data_dir, playlist, file_id, ext, changes):
    """Prevent uploading of obvious duplicate audio tracks."""
    with locked_open(os.path.join(data_dir, "index.json")) as f:
        data = json.load(f)

    addition = [c for c in changes if isinstance(c, FileAddition)]
    if addition:
        changes = [c for c in changes if isinstance(c, MetadataChange)]

        filename = [c.value for c in changes if c.key == "original_filename"][0]
        title = [c.value for c in changes if c.key == "title"][0]
        artist = [c.value for c in changes if c.key == "artist"][0]

        for entry in data.values():
            if (
                entry["original_filename"] == filename
                and entry["artist"] == artist
                and entry["title"] == title
                and entry["playlist"] == playlist
            ):
                raise UnprocessableEntity(
                    f"Duplicate file entry: {artist} - {title} ({filename})"
                )


def raw_file_processor(data_dir, playlist, fileId, ext, changes):
    """Store or delete the file in or from the file system."""
    path = os.path.join(data_dir, playlist, fileId + "." + ext)
    for change in changes:
        if isinstance(change, FileAddition):
            file_ = change.file
            if isinstance(file_, str):
                shutil.copy(file_, path)
            else:
                with open(path, "wb") as dest:
                    shutil.copyfileobj(file_, dest)
        elif isinstance(change, FileDeletion):
            if not os.path.isfile(path):
                raise NotFound()
            os.remove(path)
        elif isinstance(change, MetadataChange):
            if not os.path.isfile(path):
                raise NotFound()


def index_processor(data_dir, playlist, fileId, ext, changes, json_opts={}):
    """Save metadata in the index cache."""
    with locked_open(os.path.join(data_dir, "index.json")) as f:
        data = json.load(f)
        for change in changes:
            if isinstance(change, FileAddition):
                if fileId in data:
                    raise UnprocessableEntity("Duplicate file ID: " + fileId)
                data[fileId] = {}
            elif isinstance(change, FileDeletion):
                if fileId not in data:
                    raise NotFound()
                del data[fileId]
            elif isinstance(change, MetadataChange):
                key, value = change
                if fileId not in data:
                    raise NotFound()
                data[fileId][key] = value
        f.seek(0)
        f.truncate()
        json.dump(data, f, **json_opts)


def file_tag_processor(data_dir, playlist, fileId, ext, changes):
    """Save metadata in audio file tags."""
    with _mutagenLock:
        mutagenfile = None
        for change in changes:
            if isinstance(change, MetadataChange):
                key, value = change
                if key in TAG_KEYS:
                    if mutagenfile is None:
                        path = os.path.join(data_dir, playlist, fileId + "." + ext)
                        FileType = SUPPORTED_FILE_TYPES[ext]
                        mutagenfile = FileType(path)

                    mutagenfile[key] = str(value)

        if mutagenfile:
            mutagenfile.save()


def playlist_processor(data_dir, playlist, fileId, ext, changes):
    """Modify the playlist files.

    Remove the file from the playlist when deleting, or change it's weight
    in the playlist.
    """
    playlist_path = os.path.join(data_dir, playlist + ".m3u")
    for change in changes:
        if isinstance(change, FileDeletion):
            with locked_open(playlist_path) as f:
                lines = (s.strip() for s in f.readlines() if s != "\n")
                f.seek(0)
                f.truncate()
                for line in lines:
                    if not line.endswith(os.path.join(playlist, fileId + "." + ext)):
                        print(line, file=f)
        elif isinstance(change, MetadataChange) and change.key == "weight":
            with locked_open(playlist_path) as f:
                lines = (s.strip() for s in f.readlines() if s != "\n")
                lines = [s for s in lines if s and not s.endswith(fileId + "." + ext)]

                weight = change.value
                lines.extend([os.path.join(playlist, fileId + "." + ext)] * weight)
                f.seek(0)
                f.truncate()
                for line in lines:
                    print(line, file=f)


DEFAULT_PROCESSORS = [
    check_processor,  # type and contract check changes
    filter_duplicates_processor,  # filter obvious duplicates
    raw_file_processor,  # save file
    file_tag_processor,  # update tags
    playlist_processor,  # update playlist file
    index_processor,  # commit file to the index cache at last
]


###################
# Locking helpers #
###################

# A dict containing locks for different paths.
# Dict keys are file paths like `data/index.json`
_locks = {}

# Lock to serialize the use of non-thread-safe mutagen library
_mutagenLock = threading.Lock()


@contextlib.contextmanager
def locked_open(path, mode="r+"):
    """Lock a file for writing.

    Serialize access from other threads and processes (voluntary).
    """
    if path not in _locks:
        _locks[path] = threading.Lock()
    with _locks[path]:  # Prevent more than one thread accessing the file
        with open(path, mode) as f:
            # Prevent more than one process accessing the file (voluntarily)
            fcntl.lockf(f, fcntl.LOCK_EX)
            try:
                yield f
            finally:
                fcntl.lockf(f, fcntl.LOCK_UN)
