import os
import re
import subprocess
import sys
import uuid

from werkzeug.exceptions import NotFound, UnprocessableEntity
from werkzeug.middleware.dispatcher import DispatcherMiddleware

from . import __version__
from .api_utils import API, DummyAuth, ExternalAuth
from .player import LiquidsoapClient
from .playlist import (
    DEFAULT_PROCESSORS,
    DEFAULT_UPDATE_ANALYZERS,
    DEFAULT_UPLOAD_ANALYZERS,
    FileDeletion,
    MetadataChange,
)
from .settings import PLAYLISTS, SUPPORTED_FILE_TYPES
from .utils import _check_data_dir


def klangbecken_api(secret, data_dir, player_socket):
    """Construct the Klangbecken API WSGI application.

    This combines the two APIs for the playlists and the player
    with the authorization middleware.
    """
    playlist = playlist_api(
        data_dir, DEFAULT_UPLOAD_ANALYZERS, DEFAULT_UPDATE_ANALYZERS, DEFAULT_PROCESSORS
    )
    player = player_api(player_socket, data_dir)

    app = API()
    app.GET("/")(
        lambda request: f"Welcome to the Klangbecken API version {__version__}"
    )
    app = DispatcherMiddleware(app, {"/playlist": playlist, "/player": player})
    auth_exempts = [
        ("GET", "/player/"),
        ("GET", "/player/queue/"),
    ]
    app = ExternalAuth(app, secret, exempt=auth_exempts)
    return app


def playlist_api(  # noqa: C901
    data_dir, upload_analyzers, update_analyzers, processors
):
    """Create API for static playlists editing.

    Audio files can be uploaded into a paylist, be removed from playlist, and
    metadata about these audio files can be modified.
    """

    playlist_url = "/<any(" + ", ".join(PLAYLISTS) + "):playlist>/"
    file_url = (
        playlist_url
        + "<uuid:fileId>.<any("
        + ", ".join(SUPPORTED_FILE_TYPES.keys())
        + "):ext>"
    )

    api = API()

    @api.POST(playlist_url)
    def playlist_upload(request, playlist):
        if "file" not in request.files:
            raise UnprocessableEntity("No file attribute named 'file' found.")

        try:
            uploadFile = request.files["file"]

            ext = os.path.splitext(uploadFile.filename)[1].lower()[1:]
            fileId = str(uuid.uuid4())  # Generate new file id

            actions = []
            for analyzer in upload_analyzers:
                actions += analyzer(playlist, fileId, ext, uploadFile)

            for processor in processors:
                processor(data_dir, playlist, fileId, ext, actions)

            response = {
                change.key: change.value
                for change in actions
                if isinstance(change, MetadataChange)
            }
        finally:
            uploadFile.close()

        return {fileId: response}

    @api.PUT(file_url)
    def playlist_update(request, playlist, fileId, ext, data):
        fileId = str(fileId)

        actions = []
        for analyzer in update_analyzers:
            actions += analyzer(playlist, fileId, ext, data)

        for processor in processors:
            processor(data_dir, playlist, fileId, ext, actions)

    @api.DELETE(file_url)
    def on_playlist_delete(request, playlist, fileId, ext):
        fileId = str(fileId)

        change = [FileDeletion()]
        for processor in processors:
            processor(data_dir, playlist, fileId, ext, change)

    return api


def player_api(player_socket, data_dir):
    """Create API to interact with the Liquidsoap player.

    It supports:
     - Getting player information
     - Handling a dynamic song queue
    """
    api = API()

    @api.GET("/")
    def player_info(request):
        try:
            with LiquidsoapClient(player_socket) as client:
                return client.info()
        except (FileNotFoundError, ConnectionError):
            raise NotFound("Player not running")

    return DispatcherMiddleware(api, {"/queue": queue_api(player_socket, data_dir)})


def queue_api(player_socket, data_dir):
    api = API()

    @api.GET("/")
    def queue_list(request):
        with LiquidsoapClient(player_socket) as client:
            return client.queue()

    @api.POST("/")
    def queue_push(request, filename: str):
        filename_re = r"^({0})/([^/.]+).({1})$".format(
            "|".join(PLAYLISTS), "|".join(SUPPORTED_FILE_TYPES.keys())
        )
        if not re.match(filename_re, filename):
            raise UnprocessableEntity("Invalid file path format")

        with LiquidsoapClient(player_socket) as client:
            path = os.path.join(data_dir, filename)
            if not os.path.isfile(path):
                raise NotFound(f"File not found: {filename}")
            queue_id = client.push(path)
            return {"queue_id": queue_id}

    @api.DELETE("/<queue_id>")
    def queue_delete(request, queue_id):
        with LiquidsoapClient(player_socket) as client:
            client.delete(queue_id)

    return api


###########################
# Stand-alone Application #
###########################
def development_server(data_dir, player_socket):
    """
    Construct the stand-alone Klangbecken WSGI application for testing and development.

    * Serves data files from the data directory
    * Relays API calls to the API

    Authentication is simulated. Loudness and silence analysis are skipped,
    if ffmpeg binary is missing.
    """
    from werkzeug.middleware.shared_data import SharedDataMiddleware

    from .playlist import ffmpeg_audio_analyzer

    # Check data dirrectory structure
    _check_data_dir(data_dir)

    # Remove ffmpeg_audio_analyzer from analyzers if binary is not present
    upload_analyzers = DEFAULT_UPLOAD_ANALYZERS[:]
    try:
        subprocess.check_output("ffmpeg -version".split())
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover
        upload_analyzers.remove(ffmpeg_audio_analyzer)
        print(
            "WARNING: ffmpeg binary not found. No audio analysis is performed.",
            file=sys.stderr,
        )

    # Create a slightly customized application
    playlist = playlist_api(
        data_dir, upload_analyzers, DEFAULT_UPDATE_ANALYZERS, DEFAULT_PROCESSORS
    )

    player = player_api(player_socket, data_dir)

    dummy_app = API()
    dummy_app.GET("/")(
        lambda request: f"Welcome to the Klangbecken API version {__version__}"
    )

    api = DispatcherMiddleware(dummy_app, {"/playlist": playlist, "/player": player})
    auth_exempt = [
        ("GET", "/player/"),
        ("GET", "/player/queue/"),
    ]
    api = DummyAuth(api, "no secret", exempt=auth_exempt)

    # Serve static files from the data directory
    app = SharedDataMiddleware(dummy_app, {"/data": data_dir})
    # Relay requests to /api to the klangbecken_api instance
    app = DispatcherMiddleware(app, {"/api": api})

    return app
