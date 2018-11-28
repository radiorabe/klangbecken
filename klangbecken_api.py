#!/usr/bin/python3
from __future__ import print_function, unicode_literals, division

import collections
import functools
import json
import os
import random
import subprocess
import sys
import time
import uuid
# from collections import Counter
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


############
# HTTP API #
############
class WebAPI:

    def __init__(self, analyzers=None, processors=None):
        self.data_dir = os.environ.get('KLANGBECKEN_DATA',
                                       '/var/lib/klangbecken')
        self.secret = os.environ['KLANGBECKEN_API_SECRET']

        self.analyzers = analyzers or DEFAULT_ANALYZERS
        self.processors = processors or DEFAULT_PROCESSORS

        playlist_url = '/<any(' + ', '.join(PLAYLISTS) + '):playlist>/'
        file_url = playlist_url + '<uuid:fileId><any(' + \
            ', '.join(supported_file_types.keys()) + '):ext>'

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
            if endpoint != 'login' and (session.new or 'user' not in session):
                raise Unauthorized()
            response = getattr(self, 'on_' + endpoint)(request, **values)
        except HTTPException as e:
            response = e
        return response(environ, start_response)

    def on_login(self, request):
        if request.remote_user is None:
            raise Unauthorized()

        response = JSONResponse({'status': 'OK'})
        session = request.client_session
        session['user'] = request.environ['REMOTE_USER']
        session.save_cookie(response)
        return response

    def on_logout(self, request):
        response = JSONResponse({'status': 'OK'})
        session = request.client_session
        del session['user']
        session.save_cookie(response)
        return response

    def on_upload(self, request, playlist):
        uploadFile = request.files['files']

        # Generate id
        ext = os.path.splitext(uploadFile.filename)[1].lower()
        fileId = text_type(uuid.uuid1())

        actions = []
        for analyzer in self.analyzers:
            actions += analyzer(uploadFile)

        actions.append(MetadataChange('playlist', playlist))

        for processor in self.processors:
            processor(playlist, fileId, ext, actions)

        response = {}
        for change in actions:
            if isinstance(change, MetadataChange):
                response[change.key] = change.value

        return JSONResponse({fileId: response})

    def on_update(self, request, playlist, fileId, ext):
        if not os.path.isfile(os.path.join(self.data_dir, 'files', fileId)):
            raise NotFound()

        allowed_changes = ['artist', 'title', 'album', 'count']
        changes = []

        try:
            data = json.loads(request.data)
            if not isinstance(data, dict):
                raise UnprocessableEntity('Cannot parse PUT request')
            for key, value in data:
                if key not in allowed_changes:
                    raise UnprocessableEntity('Cannot parse PUT request')
                changes.append(MetadataChange(fileId, key, value))
            raise UnprocessableEntity('Cannot parse PUT request')
        except JSONDecodeError:

        # typecheck_changes(changes)
        for processor in self.processors:
            processor(playlist, fileId, ext, changes)

        return JSONResponse({'status': 'OK'})

    def on_delete(self, request, playlist, fileId, ext):
        fileId = text_type(fileId)
        path = os.path.join(self.data_dir, playlist, fileId + ext)
        if not os.path.isfile(path):
            raise NotFound()

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


###############
# Description #
###############
FileAddition = collections.namedtuple('FileAddition', ('file'))
MetadataChange = collections.namedtuple('MetadataChange', ('key', 'value'))
FileDeletion = collections.namedtuple('FileDeletion', ())

supported_file_types = {
    '.mp3': mutagen.mp3.MP3,
    '.ogg': mutagen.oggvorbis.OggVorbis,
    '.flac': mutagen.flac.FLAC,
}

# register the TXXX key so that we can access it later as
EasyID3.RegisterTXXXKey(key='track_gain', desc='REPLAYGAIN_TRACK_GAIN')
EasyID3.RegisterTXXXKey(key='cue_in', desc='CUE_IN')
EasyID3.RegisterTXXXKey(key='cue_out', desc='CUE_OUT')
EasyID3.RegisterTXXXKey(key='original_filename', desc='ORIGINAL_FILENAME')
EasyID3.RegisterTXXXKey(key='import_timestamp', desc='IMPORT_TIMESTAMP')
EasyID3.RegisterTXXXKey(key='playlist', desc='PLAYLIST')


#############
# Analyzers #
#############
def raw_file_analyzer(file_):
    if not file_:
        raise UnprocessableEntity('No File found')

    ext = os.path.splitext(file_.filename)[1].lower()
    if ext not in supported_file_types.keys():
        raise UnprocessableEntity('Unsupported file extension: %s' % ext)

    return [
        FileAddition(file_),
        MetadataChange('original_filename', file_.filename),
        MetadataChange('import_timestamp', time.time()),
        MetadataChange('count', 1),
    ]


def file_tag_analyzer(file_):
    mutagenfile = mutagen.File(file_, easy=True)

    if mutagenfile is None:
        raise UnprocessableEntity('Cannot read file metadata')

    if not any(isinstance(mutagenfile, file_type)
               for file_type in supported_file_types.values()):
        raise UnprocessableEntity('Unsupported file type: %s' %
                                  type(mutagenfile))

    return [
        MetadataChange('artist', mutagenfile.get('artist', [''])[0]),
        MetadataChange('title', mutagenfile.get('title', [''])[0]),
        MetadataChange('album', mutagenfile.get('album', [''])[0]),
        MetadataChange('length', mutagenfile.info.length),
    ]


def silan_silence_analyzer(file_):
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


def noop_silence_analyzer(file_):
    return [
        MetadataChange('cue_in', 0.0),
        MetadataChange('cue_out', 100.0),
    ]


def bs1770gain_loudness_analyzer(file_):
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


def noop_loudness_analyzer(file_):
    return [
        MetadataChange('track_gain', '0 dB')
    ]


DEFAULT_ANALYZERS = [
    raw_file_analyzer,
    file_tag_analyzer,
    silan_silence_analyzer,
    bs1770gain_loudness_analyzer
]


def __get_path(first, second=None, ext=None):
    data_dir = os.environ.get('KLANGBECKEN_DATA', '/var/lib/klangbecken')
    if second is None:
        return os.path.join(data_dir, first)
    elif ext is None:
        return os.path.join(data_dir, first, second)
    else:
        return os.path.join(data_dir, first, second + ext)


##############
# Processors #
##############
def raw_file_processor(playlist, fileId, ext, changes):
    for change in changes:
        if isinstance(change, FileAddition):
            file_ = change.file
            file_.save(__get_path(playlist, fileId, ext))
        elif isinstance(change, FileDeletion):
            os.remove(__get_path(playlist, fileId, ext))


def index_processor(playlist, fileId, ext, changes, json_opts={}):
    indexJson = __get_path('index.json')
    # FIXME: locking
    data = json.load(open(indexJson))
    for change in changes:
        if isinstance(change, FileAddition):
            data[fileId] = {
                'fileId': fileId,
                'ext': ext,
                'playlist': playlist,
            }
        elif isinstance(change, FileDeletion):
            del data[fileId]
        elif isinstance(change, MetadataChange):
            key, value = change
            data[fileId][key] = value
        else:
            assert False  # must not happen

    # FIXME: is this automatic dereferencing thing allowed with files?
    json.dump(data, open(indexJson, 'w'), **json_opts)


def file_tag_processor(playlist, fileId, ext, changes):
    mutagenfile = None
    changed = False
    for change in changes:
        if isinstance(change, MetadataChange):
            if mutagenfile is None:
                path = __get_path(playlist, fileId, ext)
                mutagenfile = mutagen.File(path, easy=True)
            key, value = change
            mutagenfile[key] = text_type(value)
            changed = True

    if changed:
        mutagenfile.save()


def playlist_processor(playlist, fileId, ext, changes):
    playlist = __get_path(playlist + '.m3u')
    for change in changes:
        if isinstance(change, FileDeletion):
            lines = open(playlist).readlines()
            with open(playlist, 'w') as f:
                for line in lines:
                    if fileId not in line:
                        print(line.strip(), file=f)
        elif isinstance(change, MetadataChange) and change.key == 'count':
            lines = open(playlist).readlines()
            lines = [line.strip() for line in lines if fileId not in line]
            count = change.value
            lines.append([os.path.join(playlist, fileId + ext)] * count)
            random.shuffle(lines)  # TODO: custom shuffling?
            with open(playlist, 'w') as f:
                print('\n'.join(lines), file=f)


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

    Authentication is simulated.
    """

    def __init__(self):
        from werkzeug.wsgi import DispatcherMiddleware, SharedDataMiddleware

        # Assemble useful paths
        current_path = os.path.dirname(os.path.realpath(__file__))
        data_full_path = os.path.join(current_path, 'data')
        dist_dir = open(os.path.join(current_path, '.dist_dir')).read().strip()
        dist_full_path = os.path.join(current_path, dist_dir)

        # Set environment variables needed by the KlangbeckenAPI
        os.environ['KLANGBECKEN_DATA'] = data_full_path
        os.environ['KLANGBECKEN_API_SECRET'] = \
            ''.join(random.sample('abcdefghijklmnopqrstuvwxyz', 20))

        # Return 404 Not Found by default
        app = NotFound()
        # Serve static files from the dist and data directories
        app = SharedDataMiddleware(app, {'': dist_full_path,
                                         '/data': data_full_path})
        # Relay requests to /api to the KlangbeckenAPI instance
        app = DispatcherMiddleware(app, {'/api': WebAPI(
            analyzers=[
                raw_file_analyzer,
                file_tag_analyzer,
                noop_silence_analyzer,
                noop_loudness_analyzer
            ],
            processors=[
                raw_file_processor,
                functools.partial(
                    index_processor,
                    json_opts={'indent': 2, 'sort_keys': True}
                ),
                file_tag_processor,
                playlist_processor,
            ]
        )})

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
def _check_and_crate_data_dir():
    """
    Create local data directory structure for testing and development
    """
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
    for path in [data_dir] + [os.path.join(data_dir, d) for d in PLAYLISTS]:
        if not os.path.isdir(path):
            os.mkdir(path)
    for path in [os.path.join(data_dir, d + '.m3u') for d in PLAYLISTS]:
        if not os.path.isfile(path):
            open(path, 'a').close()

    # FIXME: create index.json


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
    application = WebAPI()
