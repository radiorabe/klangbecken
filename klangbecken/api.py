import datetime
import functools
import json
import os
import subprocess
import sys
import uuid

import jwt
from werkzeug.exceptions import (
    HTTPException,
    NotFound,
    Unauthorized,
    UnprocessableEntity,
)
from werkzeug.routing import Map, Rule
from werkzeug.wrappers import Request, Response

from .playlist import (
    DEFAULT_PROCESSORS,
    DEFAULT_UPDATE_ANALYZERS,
    DEFAULT_UPLOAD_ANALYZERS,
    FileDeletion,
    MetadataChange,
    playnext_processor,
)
from .settings import PLAYLISTS, SUPPORTED_FILE_TYPES
from .utils import _check_data_dir


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
        token = jwt.encode(claims, self.secret, algorithm="HS256")

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

        token = jwt.encode(claims, self.secret, algorithm="HS256")

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

        from .playlist import (
            check_processor,
            ffmpeg_audio_analyzer,
            file_tag_processor,
            filter_duplicates_processor,
            index_processor,
            mutagen_tag_analyzer,
            playlist_processor,
            raw_file_analyzer,
            raw_file_processor,
        )

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
                [
                    ("Content-Type", "text/plain"),
                    ("Content-Length", str(len(msg))),
                ],
            )
            return [msg]

        return self.app(environ, start_response)
