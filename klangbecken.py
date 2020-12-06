#!/usr/bin/env python3
##############################################################################
# klangbecken_api.py - Klangbecken API                                       #
##############################################################################
#
# Copyright 2017-2020 Radio Bern RaBe, Switzerland, https://rabe.ch
#
# This program is free software: you can redistribute it and/or
# modify it under the terms of the GNU Affero General Public
# License as published  by the Free Software Foundation, version
# 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public
# License  along with this program.
# If not, see <http://www.gnu.org/licenses/>.
#
# Please submit enhancements, bugfixes or comments via:
# https://github.com/radiorabe/klangbecken

import collections
import contextlib
import csv
import datetime
import fcntl
import functools
import json
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import uuid

import jwt
import mutagen
import mutagen.easyid3
import mutagen.flac
import mutagen.mp3
import mutagen.oggvorbis
import pkg_resources
from werkzeug.exceptions import (
    HTTPException,
    NotFound,
    Unauthorized,
    UnprocessableEntity,
)
from werkzeug.routing import Map, Rule
from werkzeug.wrappers import Request, Response

try:
    __version__ = pkg_resources.get_distribution("klangbecken").version
except pkg_resources.DistributionNotFound:  # pragma: no cover
    __version__ = "development version"


############
# Settings #
############
PLAYLISTS = ("music", "classics", "jingles")

# Map file extension to mutagen class for all supported file types
SUPPORTED_FILE_TYPES = {
    "mp3": mutagen.mp3.EasyMP3,
    "ogg": mutagen.oggvorbis.OggVorbis,
    "flac": mutagen.flac.FLAC,
}

ISO8601_RE = (
    # Date
    r"(-?(?:[1-9][0-9]*)?[0-9]{4})-(1[0-2]|0[1-9])-(3[01]|0[1-9]|[12][0-9])T"
    # Time (optionally with a fraction of a second)
    r"(2[0-3]|[01][0-9]):([0-5][0-9]):([0-5][0-9])(\.[0-9]+)?"
    # Timezone information (Z for UTC or +/- offset from UTC)
    r"(Z|[+-](?:2[0-3]|[01][0-9]):[0-5][0-9])?"
)

# Attention: The order of metadata keys is used when writing CSV log files.
# Do not reorder or delete metadata keys. Renaming or addition at the end is
# okay.
ALLOWED_METADATA = {
    "id": (str, r"^[a-z0-9]{8}-([a-z0-9]{4}-){3}[a-z0-9]{12}$"),
    "ext": (str, lambda ext: ext in SUPPORTED_FILE_TYPES.keys()),
    "playlist": (str, lambda pl: pl in PLAYLISTS),
    "original_filename": str,
    "import_timestamp": ISO8601_RE,
    "weight": (int, lambda c: c >= 0),
    "artist": str,
    "title": str,
    "album": str,
    "length": (float, lambda n: n >= 0.0),
    "track_gain": (str, r"^[+-]?[0-9]*(\.[0-9]*) dB$"),
    "cue_in": (float, lambda n: n >= 0.0),
    "cue_out": (float, lambda n: n >= 0.0),
    "play_count": (int, lambda n: n >= 0),
    "last_play": (str, r"^(^$)|(^{0}$)".format(ISO8601_RE)),
}

UPDATE_KEYS = "artist title album weight".split()
TAG_KEYS = (
    "artist title album cue_in cue_out track_gain original_filename import_timestamp"
).split()


####################
# Action-"Classes" #
####################
FileAddition = collections.namedtuple("FileAddition", ("file"))
MetadataChange = collections.namedtuple("MetadataChange", ("key", "value"))
FileDeletion = collections.namedtuple("FileDeletion", ())


#############
# Analyzers #
#############
def raw_file_analyzer(playlist, fileId, ext, file_):
    if not file_:
        raise UnprocessableEntity("No File found")

    if ext not in SUPPORTED_FILE_TYPES.keys():
        raise UnprocessableEntity(f"Unsupported file extension: {ext}")

    # Be compatible with werkzeug.datastructures.FileStorage and plain files
    filename = file_.filename if hasattr(file_, "filename") else file_.name

    return [
        FileAddition(file_),
        MetadataChange("id", fileId),
        MetadataChange("ext", ext),
        MetadataChange("playlist", playlist),
        MetadataChange("original_filename", filename),
        MetadataChange("import_timestamp", datetime.datetime.now().isoformat()),
        MetadataChange("weight", 1),
        MetadataChange("play_count", 0),
        MetadataChange("last_play", ""),
    ]


def mutagen_tag_analyzer(playlist, fileId, ext, file_):
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

    gain = trackgain_re.search(output).groups()[0]
    silence_times = re.findall(silence_re, output)
    silence_times = [(name, float(value)) for name, value in silence_times]

    # Last 'start' time is cue_out
    reversed_times = reversed(silence_times)
    cue_out = next(
        (t[1] for t in reversed_times if t[0] == "start")
    )  # pragma: no cover

    if -0.05 < cue_out < 0.0:  # pragma: no cover
        cue_out = 0.0

    # From remaining times, first 'end' time is cue_in, otherwise 0.0
    remaining_times = reversed(list(reversed_times))
    cue_in = next((t[1] for t in remaining_times if t[0] == "end"), 0.0)

    # Fix small negative values for cue_in
    if -0.05 < cue_in < 0.0:  # pragma: no cover
        cue_in = 0.0

    # Fix clearly too large cue_in values
    # Note: ffmpeg is not very reliable with it's cue point calculation,
    # especially with cue_in. Any value, that is clearly to large (>5s) is
    # reset.
    if cue_in > 5.0:
        cue_in = 0.0

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
def check_processor(data_dir, playlist, fileId, ext, changes):  # noqa: C901
    for change in changes:
        if isinstance(change, MetadataChange):
            key, val = change

            if key not in ALLOWED_METADATA.keys():
                raise UnprocessableEntity(f"Invalid metadata key: {key}")

            checks = ALLOWED_METADATA[key]
            if not isinstance(checks, (list, tuple)):
                checks = (checks,)

            for check in checks:
                if isinstance(check, type):
                    if not isinstance(val, check):
                        raise UnprocessableEntity(
                            f'Invalid data format for "{key}": Type error '
                            f"(expected {check.__name__}, "
                            f"got {type(val).__name__})."
                        )
                elif callable(check):
                    if not check(val):
                        raise UnprocessableEntity(
                            f'Invalid data format for "{key}": Check failed '
                            f'(value: "{val}").'
                        )
                elif isinstance(check, str):
                    if re.match(check, val) is None:
                        raise UnprocessableEntity(
                            f'Invalid data format for "{key}": Regex check '
                            f'failed (value: "{val}", regex: "{check}").'
                        )
                else:
                    raise NotImplementedError()
        elif isinstance(change, (FileAddition, FileDeletion)):
            pass
        else:
            raise ValueError("Invalid action class")


def filter_duplicates_processor(data_dir, playlist, file_id, ext, changes):
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
                    "Duplicate file entry:\n"
                    + artist
                    + " - "
                    + title
                    + " ("
                    + filename
                    + ")"
                )


def raw_file_processor(data_dir, playlist, fileId, ext, changes):
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


mutagen.easyid3.EasyID3.RegisterTXXXKey(key="cue_in", desc="CUE_IN")
mutagen.easyid3.EasyID3.RegisterTXXXKey(key="cue_out", desc="CUE_OUT")
mutagen.easyid3.EasyID3.RegisterTXXXKey(key="track_gain", desc="REPLAYGAIN_TRACK_GAIN")
mutagen.easyid3.EasyID3.RegisterTXXXKey(
    key="original_filename", desc="ORIGINAL_FILENAME"
)
mutagen.easyid3.EasyID3.RegisterTXXXKey(key="import_timestamp", desc="IMPORT_TIMESTAMP")
mutagen.easyid3.EasyID3.RegisterTXXXKey(key="last_play", desc="LAST_PLAY")


def file_tag_processor(data_dir, playlist, fileId, ext, changes):
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
                random.shuffle(lines)  # TODO: custom shuffling?
                f.seek(0)
                f.truncate()
                for line in lines:
                    print(line, file=f)


DEFAULT_PROCESSORS = [
    check_processor,  # type and contract check changes
    filter_duplicates_processor,
    raw_file_processor,  # save file
    file_tag_processor,  # update tags
    playlist_processor,  # update playlist file
    index_processor,  # commit file to index at last
]


def playnext_processor(data_dir, data):
    if not isinstance(data, dict):
        raise UnprocessableEntity("Invalid data format: " "associative array expected")
    if "file" not in data:
        raise UnprocessableEntity("Invalid data format: " 'Key "file" not found')

    filename = data["file"]
    filename_re = r"^({0})/([^/.]+)\.({1})$".format(
        "|".join(PLAYLISTS), "|".join(SUPPORTED_FILE_TYPES.keys())
    )
    if not re.match(filename_re, filename):
        raise UnprocessableEntity("Invalid file path format")

    path = os.path.join(data_dir, filename)
    if not os.path.isfile(path):
        raise NotFound()

    with locked_open(os.path.join(data_dir, "prio.m3u")) as f:
        f.seek(0)
        f.truncate()
        print(filename, file=f)


# Locking Helper

_locks = {}
_mutagenLock = threading.Lock()


@contextlib.contextmanager
def locked_open(path, mode="r+"):
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


############
# HTTP API #
############
class KlangbeckenAPI:
    def __init__(
        self,
        data_dir,
        secret,
        upload_analyzers=DEFAULT_UPLOAD_ANALYZERS,
        update_analyzers=DEFAULT_UPDATE_ANALYZERS,
        processors=DEFAULT_PROCESSORS,
        disable_auth=False,
    ):
        self.data_dir = data_dir
        self.secret = secret
        self.upload_analyzers = upload_analyzers
        self.update_analyzers = update_analyzers
        self.processors = processors
        self.do_auth = not disable_auth

        playlist_url = "/<any(" + ", ".join(PLAYLISTS) + "):playlist>/"
        file_url = (
            playlist_url
            + "<uuid:fileId>.<any("
            + ", ".join(SUPPORTED_FILE_TYPES.keys())
            + "):ext>"
        )

        self.url_map = Map(
            rules=(
                Rule("/auth/login/", methods=("GET", "POST"), endpoint="login"),
                Rule("/auth/renew/", methods=("POST",), endpoint="renew"),
                Rule(playlist_url, methods=("POST",), endpoint="upload"),
                Rule(file_url, methods=("PUT",), endpoint="update"),
                Rule(file_url, methods=("DELETE",), endpoint="delete"),
                Rule("/playnext/", methods=("POST",), endpoint="play_next"),
            )
        )

    def __call__(self, environ, start_response):
        try:
            request = Request(environ)
            adapter = self.url_map.bind_to_environ(environ)
            endpoint, values = adapter.match()

            # Check authorization
            if self.do_auth and endpoint not in ("login", "renew"):
                if "Authorization" not in request.headers:
                    raise Unauthorized("No authorization header supplied")

                auth = request.headers["Authorization"]
                if not auth.startswith("Bearer "):
                    raise Unauthorized("Invalid authorization header")

                token = auth[len("Bearer ") :]
                try:
                    jwt.decode(
                        token,
                        self.secret,
                        algorithms=["HS256"],
                        options={"require_exp": True, "require_iat": True},
                    )
                except jwt.InvalidTokenError:
                    raise Unauthorized("Invalid token")

            # Dispatch request
            response = getattr(self, "on_" + endpoint)(request, **values)
        except HTTPException as e:
            response = JSONResponse(
                {"code": e.code, "name": e.name, "description": e.description},
                status=e.code,
            )
        return response(environ, start_response)

    def on_login(self, request):
        if request.remote_user is None:
            raise Unauthorized()

        user = request.remote_user
        now = datetime.datetime.utcnow()
        claims = {"user": user, "iat": now, "exp": now + datetime.timedelta(minutes=15)}
        token = str(jwt.encode(claims, self.secret, algorithm="HS256"), "ascii")

        return JSONResponse({"token": token})

    def on_renew(self, request):  # noqa: C901
        try:
            data = json.loads(str(request.data, "utf-8"))
        except (UnicodeDecodeError, TypeError):
            raise UnprocessableEntity(
                "Cannot parse POST request: " "invalid UTF-8 data"
            )
        except ValueError:
            raise UnprocessableEntity("Cannot parse POST request: " "invalid JSON")
        if not isinstance(data, dict):
            raise UnprocessableEntity(
                "Invalid data format: " "associative array expected"
            )
        if "token" not in data:
            raise UnprocessableEntity("Invalid data format: " 'Key "token" not found')

        token = data["token"]

        now = datetime.datetime.utcnow()
        try:
            # Valid tokens can always be renewed withing their short lifetime,
            # independent of the issuing date
            claims = jwt.decode(
                token,
                self.secret,
                algorithms=["HS256"],
                options={"require_exp": True, "require_iat": True},
            )
        except jwt.ExpiredSignatureError:
            try:
                # Expired tokens can be renewed for at most one week after the
                # first issuing date
                claims = jwt.decode(
                    token,
                    self.secret,
                    algorithms=["HS256"],
                    options={
                        "require_exp": True,
                        "require_iat": True,
                        "verify_exp": False,
                    },
                )
                issued_at = datetime.datetime.utcfromtimestamp(claims["iat"])
                if issued_at + datetime.timedelta(days=7) < now:
                    raise Unauthorized()
            except jwt.InvalidTokenError:
                raise Unauthorized()
        except jwt.InvalidTokenError:
            raise Unauthorized()

        claims["exp"] = now + datetime.timedelta(minutes=15)

        token = str(jwt.encode(claims, self.secret, algorithm="HS256"), "ascii")

        return JSONResponse({"token": token})

    def on_upload(self, request, playlist):
        if "file" not in request.files:
            raise UnprocessableEntity("No attribute named 'file' found.")

        try:
            uploadFile = request.files["file"]

            ext = os.path.splitext(uploadFile.filename)[1].lower()[1:]
            fileId = str(uuid.uuid4())  # Generate new file id

            actions = []
            for analyzer in self.upload_analyzers:
                actions += analyzer(playlist, fileId, ext, uploadFile)

            for processor in self.processors:
                processor(self.data_dir, playlist, fileId, ext, actions)

            response = {}
            for change in actions:
                if isinstance(change, MetadataChange):
                    response[change.key] = change.value
        finally:
            uploadFile.close()

        return JSONResponse({fileId: response})

    def on_update(self, request, playlist, fileId, ext):
        fileId = str(fileId)

        actions = []
        try:
            data = json.loads(str(request.data, "utf-8"))
            for analyzer in self.update_analyzers:
                actions += analyzer(playlist, fileId, ext, data)

        except (UnicodeDecodeError, TypeError):
            raise UnprocessableEntity("Cannot parse PUT request: " "invalid UTF-8 data")
        except ValueError:
            raise UnprocessableEntity("Cannot parse PUT request: " "invalid JSON")

        for processor in self.processors:
            processor(self.data_dir, playlist, fileId, ext, actions)

        return JSONResponse({"status": "OK"})

    def on_delete(self, request, playlist, fileId, ext):
        fileId = str(fileId)

        change = [FileDeletion()]
        for processor in self.processors:
            processor(self.data_dir, playlist, fileId, ext, change)

        return JSONResponse({"status": "OK"})

    def on_play_next(self, request):
        try:
            data = json.loads(str(request.data, "utf-8"))
            playnext_processor(self.data_dir, data)

        except (UnicodeDecodeError, TypeError):
            raise UnprocessableEntity("Cannot parse PUT request: " "invalid UTF-8 data")
        except ValueError:
            raise UnprocessableEntity("Cannot parse PUT request: " "invalid JSON")

        return JSONResponse({"status": "OK"})


class JSONResponse(Response):
    """JSON response helper creates JSON responses."""

    def __init__(self, data, status=200, **json_opts):
        super(JSONResponse, self).__init__(
            json.dumps(data, **json_opts), status=status, mimetype="text/json"
        )


class JSONSerializer:
    @staticmethod
    def dumps(obj):
        # UTF-8 encoding is default in Python 3+
        return json.dumps(obj).encode("utf-8")

    @staticmethod
    def loads(serialized):
        # UTF-8 encoding is default in Python 3+
        return json.loads(str(serialized, "utf-8"))


###########################
# Stand-alone Application #
###########################
class StandaloneWebApplication:
    """
    Stand-alone Klangbecken WSGI application for testing and development.

    * Serves data files from the data directory
    * Relays API calls to the KlangbeckenAPI instance

    Authentication is disabled. Loudness and silence analysis are skipped,
    if ffmpeg binary is missing.
    """

    def __init__(self, data_dir, secret):
        from werkzeug.middleware.dispatcher import DispatcherMiddleware
        from werkzeug.middleware.shared_data import SharedDataMiddleware

        # Check data directory structure
        _check_data_dir(data_dir)

        # Only add ffmpeg_audio_analyzer to analyzers if binary is present
        upload_analyzers = [raw_file_analyzer, mutagen_tag_analyzer]
        try:
            subprocess.check_output("ffmpeg -version".split())
            upload_analyzers.append(ffmpeg_audio_analyzer)
        except (OSError, subprocess.CalledProcessError):  # pragma: no cover
            print(
                "WARNING: ffmpeg binary not found. " "No audio analysis is performed.",
                file=sys.stderr,
            )

        # Slightly modify processors, such that index.json is pretty-printed
        processors = [
            check_processor,
            filter_duplicates_processor,
            raw_file_processor,
            functools.partial(
                index_processor, json_opts={"indent": 2, "sort_keys": True}
            ),
            file_tag_processor,
            playlist_processor,
        ]

        # Create customized KlangbeckenAPI application
        api = KlangbeckenAPI(
            data_dir, secret, upload_analyzers=upload_analyzers, processors=processors
        )

        # Return 404 Not Found by default
        app = NotFound()
        # Serve static files from the data directory
        app = SharedDataMiddleware(app, {"/data": data_dir})
        # Relay requests to /api to the KlangbeckenAPI instance
        app = DispatcherMiddleware(app, {"/api": api})

        self.app = app

    def __call__(self, environ, start_response):
        # Insert dummy user for authentication
        # (normally done externally)
        environ["REMOTE_USER"] = "dummyuser"

        # Be nice
        if environ["PATH_INFO"] == "/":
            msg = b"Welcome to the Klangbecken API!\n"
            start_response(
                "200 OK",
                [("Content-Type", "text/plain"), ("Content-Length", str(len(msg)))],
            )
            return [msg]

        return self.app(environ, start_response)


###########
# Helpers #
###########
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
    for path in [os.path.join(data_dir, d + ".m3u") for d in PLAYLISTS + ("prio",)]:
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


################
# Entry points #
################
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


if __name__ == "__main__":
    # Enable development mode, when being called directly with
    # $ python klangbecken.py
    main(dev_mode=True)

# -*- mode: python; indent-tabs-mode: nil; tab-width: 4 -*-
