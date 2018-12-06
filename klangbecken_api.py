#!/usr/bin/python3
from __future__ import print_function, unicode_literals, division

import collections
import fcntl
import functools
import json
import os
import random
import subprocess
import sys
import time
import uuid
from xml.etree import ElementTree

import mutagen
import mutagen.mp3
import mutagen.oggvorbis
import mutagen.flac
from mutagen.easyid3 import EasyID3

from six import text_type

from werkzeug.contrib.securecookie import SecureCookie
from werkzeug.exceptions import (HTTPException, UnprocessableEntity, NotFound,
                                 Unauthorized)
from werkzeug.routing import Map, Rule
from werkzeug.wrappers import Request, Response

try:
    from json.decoder import JSONDecodeError
except ImportError:
    JSONDecodeError = ValueError


PLAYLISTS = ('music', 'jingles')

SUPPORTED_FILE_TYPES = {
    '.mp3': mutagen.mp3.EasyMP3,
    '.ogg': mutagen.oggvorbis.OggVorbis,
    '.flac': mutagen.flac.FLAC,
}

ALLOWED_METADATA_CHANGES = {
    'artist': text_type,
    'title': text_type,
    'album': text_type,
    'count': int,
}

####################
# Action-"Classes" #
####################
FileAddition = collections.namedtuple('FileAddition', ('file'))
MetadataChange = collections.namedtuple('MetadataChange', ('key', 'value'))
FileDeletion = collections.namedtuple('FileDeletion', ())


############
# HTTP API #
############
class KlangbeckenAPI:

    def __init__(self, upload_analyzers=None, update_analyzers=None,
                 processors=None, disable_auth=False):
        self.data_dir = os.environ.get('KLANGBECKEN_DATA',
                                       '/var/lib/klangbecken')
        self.secret = os.environ['KLANGBECKEN_API_SECRET']

        self.upload_analyzers = upload_analyzers or DEFAULT_UPLOAD_ANALYZERS
        self.update_analyzers = update_analyzers or DEFAULT_UPDATE_ANALYZERS
        self.processors = processors or DEFAULT_PROCESSORS
        self.auth = not disable_auth

        playlist_url = '/<any(' + ', '.join(PLAYLISTS) + '):playlist>/'
        file_url = playlist_url + '<uuid:fileId><any(' + \
            ', '.join(SUPPORTED_FILE_TYPES.keys()) + '):ext>'

        self.url_map = Map(rules=(
            Rule('/login/', methods=('GET', 'POST'), endpoint='login'),
            Rule('/logout/', methods=('POST',), endpoint='logout'),

            Rule(playlist_url, methods=('POST',), endpoint='upload'),
            Rule(file_url, methods=('PUT',), endpoint='update'),
            Rule(file_url, methods=('DELETE',), endpoint='delete'),
        ))

    def __call__(self, environ, start_response):
        adapter = self.url_map.bind_to_environ(environ)
        request = Request(environ)
        session = SecureCookie.load_cookie(request, secret_key=self.secret)
        request.client_session = session
        try:
            endpoint, values = adapter.match()
            if self.auth and endpoint != 'login' and \
                    (session.new or 'user' not in session):
                raise Unauthorized()
            response = getattr(self, 'on_' + endpoint)(request, **values)
        except HTTPException as e:
            response = e
        return response(environ, start_response)

    def on_login(self, request):
        if request.remote_user is None:
            raise Unauthorized()

        response = JSONResponse({'status': 'OK'})
        if self.auth:
            session = request.client_session
            session['user'] = request.environ['REMOTE_USER']
            session.save_cookie(response)
        return response

    def on_logout(self, request):
        response = JSONResponse({'status': 'OK'})
        if self.auth:
            session = request.client_session
            del session['user']
            session.save_cookie(response)
        return response

    def on_upload(self, request, playlist):
        if 'file' not in request.files:
            raise UnprocessableEntity('No attribute named \'file\' found.')

        uploadFile = request.files['file']

        ext = os.path.splitext(uploadFile.filename)[1].lower()
        fileId = text_type(uuid.uuid1())   # Generate new file id

        actions = []
        for analyzer in self.upload_analyzers:
            actions += analyzer(playlist, fileId, ext, uploadFile)

        for processor in self.processors:
            processor(playlist, fileId, ext, actions)

        response = {}
        for change in actions:
            if isinstance(change, MetadataChange):
                response[change.key] = change.value

        return JSONResponse({fileId: response})

    def on_update(self, request, playlist, fileId, ext):
        fileId = text_type(fileId)

        actions = []
        try:
            data = json.loads(text_type(request.data, 'utf-8'))
            for analyzer in self.update_analyzers:
                actions += analyzer(playlist, fileId, ext, data)

        except (UnicodeDecodeError, TypeError):
            raise UnprocessableEntity('Cannot parse PUT request: ' +
                                      ' not valid UTF-8 data')
        except JSONDecodeError:
            raise UnprocessableEntity('Cannot parse PUT request: ' +
                                      ' not valid JSON')

        for processor in self.processors:
            processor(playlist, fileId, ext, actions)

        return JSONResponse({'status': 'OK'})

    def on_delete(self, request, playlist, fileId, ext):
        fileId = text_type(fileId)

        change = [FileDeletion()]
        for processor in self.processors:
            processor(playlist, fileId, ext, change)

        return JSONResponse({'status': 'OK'})


class JSONResponse(Response):
    """
    JSON response helper
    """
    def __init__(self, data, **json_opts):
        super(JSONResponse, self).__init__(json.dumps(data, **json_opts),
                                           mimetype='text/json')


#############
# Analyzers #
#############
def raw_file_analyzer(playlist, fileId, ext, file_, ):
    if not file_:
        raise UnprocessableEntity('No File found')

    if ext not in SUPPORTED_FILE_TYPES.keys():
        raise UnprocessableEntity('Unsupported file extension: %s' % ext)

    return [
        FileAddition(file_),
        MetadataChange('playlist', playlist),
        MetadataChange('id', fileId),
        MetadataChange('ext', ext),
        MetadataChange('original_filename', file_.filename),
        MetadataChange('import_timestamp', time.time()),
        MetadataChange('count', 1),
    ]


def mutagen_tag_analyzer(playlist, fileId, ext, file_):
    MutagenFileType = SUPPORTED_FILE_TYPES[ext]
    try:
        mutagenfile = MutagenFileType(file_)
    except mutagen.MutagenError:
        raise UnprocessableEntity('Unsupported file type: ' +
                                  'Cannot read metadata.')
    changes = [
        MetadataChange('artist', mutagenfile.get('artist', [''])[0]),
        MetadataChange('title', mutagenfile.get('title', [''])[0]),
        MetadataChange('album', mutagenfile.get('album', [''])[0]),
        MetadataChange('length', mutagenfile.info.length),
    ]
    # Seek back to the start of the file for whoever comes next
    file_.stream.seek(0)
    return changes


def silan_silence_analyzer(playlist, fileId, ext, file_):
    silan_cmd = [
        '/usr/bin/silan', '--format', 'json', file_.filename
    ]
    try:
        output = subprocess.check_output(silan_cmd)
        cue_points = json.loads(output)['sound'][0]
    except:   # noqa: E722
        raise UnprocessableEntity('Silence analysis failed')
    return [
        MetadataChange('cue_in', cue_points[0]),
        MetadataChange('cue_out', cue_points[0]),
    ]


def bs1770gain_loudness_analyzer(playlist, fileId, ext, file_):
    bs1770gain_cmd = [
        "/usr/bin/bs1770gain", "--ebu", "--xml", file_.filename
    ]
    output = subprocess.check_output(bs1770gain_cmd)
    bs1770gain = ElementTree.fromstring(output)
    # lu is in bs1770gain > album > track > integrated as an attribute
    track_gain = bs1770gain.find('./album/track/integrated').attrib['lu']
    return [
        MetadataChange('track_gain', track_gain + ' dB')
    ]


DEFAULT_UPLOAD_ANALYZERS = [
    raw_file_analyzer,
    mutagen_tag_analyzer,
    silan_silence_analyzer,
    bs1770gain_loudness_analyzer,
]


def update_analyzer(playlist, fileId, ext, data):
    changes = []
    if not isinstance(data, dict):
        raise UnprocessableEntity('Cannot parse PUT request: ' +
                                  'Expected a dict.')
    for key, value in data.items():
        if key not in ALLOWED_METADATA_CHANGES.keys():
            raise UnprocessableEntity('Cannot parse PUT request: ' +
                                      'Key not allowed: ' + key)
        if not isinstance(value, ALLOWED_METADATA_CHANGES[key]):
            raise UnprocessableEntity(
                'Cannot parse PUT request: Type error ' +
                '(expected %s, got %s).' %
                (ALLOWED_METADATA_CHANGES[key], type(value).__name__)
            )
        changes.append(MetadataChange(key, value))
    return changes


DEFAULT_UPDATE_ANALYZERS = [update_analyzer]


##############
# Processors #
##############
def raw_file_processor(playlist, fileId, ext, changes):
    path = _get_path(playlist, fileId, ext)
    for change in changes:
        if isinstance(change, FileAddition):
            file_ = change.file
            file_.save(path)
        elif isinstance(change, FileDeletion):
            if not os.path.isfile(path):
                raise NotFound()
            os.remove(path)
        elif isinstance(change, MetadataChange):
            if not os.path.isfile(path):
                raise NotFound()


def index_processor(playlist, fileId, ext, changes, json_opts={}):
    indexJson = _get_path('index.json')
    with open(indexJson, 'r+') as f:
        fcntl.lockf(f, fcntl.LOCK_EX)
        try:
            data = json.load(f)
            for change in changes:
                if isinstance(change, FileAddition):
                    if fileId in data:
                        raise UnprocessableEntity('Duplicate file ID: '
                                                  + fileId)
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
        finally:
            fcntl.lockf(f, fcntl.LOCK_UN)


TAG_KEYS = 'artist title album cue_in cue_out track_gain'.split()

EasyID3.RegisterTXXXKey(key='track_gain', desc='REPLAYGAIN_TRACK_GAIN')
EasyID3.RegisterTXXXKey(key='cue_in', desc='CUE_IN')
EasyID3.RegisterTXXXKey(key='cue_out', desc='CUE_OUT')


def file_tag_processor(playlist, fileId, ext, changes):
    mutagenfile = None
    for change in changes:
        if isinstance(change, MetadataChange):
            key, value = change
            if key in TAG_KEYS:
                if mutagenfile is None:
                    path = _get_path(playlist, fileId, ext)
                    mutagenfile = mutagen.File(path, easy=True)

                mutagenfile[key] = text_type(value)

    if mutagenfile:
        mutagenfile.save()


def playlist_processor(playlist, fileId, ext, changes):
    playlist_path = _get_path(playlist + '.m3u')
    for change in changes:
        if isinstance(change, FileDeletion):
            with open(playlist_path) as f:
                lines = (s.strip() for s in f.readlines() if s != '\n')
            with open(playlist_path, 'w') as f:
                for line in lines:
                    if not line.endswith(os.path.join(playlist, fileId + ext)):
                        print(line, file=f)
        elif isinstance(change, MetadataChange) and change.key == 'count':
            with open(playlist_path) as f:
                lines = (s.strip() for s in f.readlines() if s != '\n')
            lines = [s for s in lines if s and not s.endswith(fileId + ext)]

            count = change.value
            lines.extend([os.path.join(playlist, fileId + ext)] * count)
            random.shuffle(lines)  # TODO: custom shuffling?
            with open(playlist_path, 'w') as f:
                for line in lines:
                    print(line, file=f)


DEFAULT_PROCESSORS = [
    raw_file_processor,
    index_processor,
    file_tag_processor,
    playlist_processor,
]


###########################
# Stand-alone Application #
###########################
class StandaloneWebApplication:
    """
    Stand-alone Klangbecken WSGI application for testing and development.

    * Serves static files from the dist directory
    * Serves data files from the data directory
    * Relays API calls to the KlangbeckenAPI instance

    Authentication is disabled. Loudness and silence analysis are skipped.
    """

    def __init__(self, data_path=None):
        from werkzeug.wsgi import DispatcherMiddleware, SharedDataMiddleware

        # Assemble useful paths
        current_path = os.path.dirname(os.path.realpath(__file__))
        data_full_path = data_path or os.path.join(current_path, 'data')
        with open(os.path.join(current_path, '.dist_dir')) as f:
            dist_dir = f.read().strip()
        dist_full_path = os.path.join(current_path, dist_dir)

        # Set environment variables needed by the KlangbeckenAPI
        os.environ['KLANGBECKEN_DATA'] = data_full_path
        os.environ['KLANGBECKEN_API_SECRET'] = \
            ''.join(random.sample('abcdefghijklmnopqrstuvwxyz', 20))

        # Create slightly customized KlangbeckenAPI application
        api = KlangbeckenAPI(
            upload_analyzers=[
                raw_file_analyzer,
                mutagen_tag_analyzer,
            ],
            processors=[
                raw_file_processor,
                functools.partial(
                    index_processor,
                    json_opts={'indent': 2, 'sort_keys': True}
                ),
                file_tag_processor,
                playlist_processor,
            ],
            disable_auth=True
        )

        # Return 404 Not Found by default
        app = NotFound()
        # Serve static files from the dist and data directories
        app = SharedDataMiddleware(app, {'': dist_full_path,
                                         '/data': data_full_path})
        # Relay requests to /api to the KlangbeckenAPI instance
        app = DispatcherMiddleware(app, {'/api': api})

        self.app = app

    def __call__(self, environ, start_response):
        # Insert dummy user for authentication
        # (normally done by the apache auth module)
        environ['REMOTE_USER'] = 'dummyuser'

        # Send 'index.html' when requesting '/'
        if environ['PATH_INFO'] == '/':
            environ['PATH_INFO'] = '/index.html'

        return self.app(environ, start_response)


###########
# Helpers #
###########
def _get_path(first, second=None, ext=None):
    data_dir = os.environ.get('KLANGBECKEN_DATA', '/var/lib/klangbecken')
    if second is None:
        return os.path.join(data_dir, first)
    elif ext is None:
        return os.path.join(data_dir, first, second)
    else:
        return os.path.join(data_dir, first, second + ext)


def _check_and_crate_data_dir(data_dir=None):
    """
    Create local data directory structure for testing and development
    """
    data_dir = data_dir or \
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
    for path in [data_dir] + [os.path.join(data_dir, d) for d in PLAYLISTS]:
        if not os.path.isdir(path):
            os.mkdir(path)
    for path in [os.path.join(data_dir, d + '.m3u') for d in PLAYLISTS]:
        if not os.path.isfile(path):
            with open(path, 'a') as f:
                pass
    path = os.path.join(data_dir, 'index.json')
    if not os.path.isfile(path):
        with open(path, 'w') as f:
            f.write('{}')


###############
# Entry pints #
###############
def main():
    """
    Run server or importer locally
    """
    from werkzeug.serving import run_simple

    _check_and_crate_data_dir()

    if len(sys.argv) == 1:
        application = StandaloneWebApplication()
        run_simple('127.0.0.1', 5000, application, use_debugger=True,
                   use_reloader=True, threaded=False)
    else:
        print("${0}: No command line arguments allowed".format(sys.argv[0]),
              file=sys.stderr)


if __name__ == '__main__':
    # Run locally in stand-alone development mode
    main()
else:
    # Set up WSGI application
    application = KlangbeckenAPI()
