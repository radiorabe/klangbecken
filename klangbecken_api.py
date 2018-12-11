#!/usr/bin/python3
from __future__ import print_function, unicode_literals, division

import collections
import fcntl
import functools
import json
import os
import random
import re
import subprocess
import time
import uuid

import mutagen
import mutagen.easyid3
import mutagen.flac
import mutagen.mp3
import mutagen.oggvorbis

from six import text_type

from werkzeug.contrib.securecookie import SecureCookie
from werkzeug.exceptions import (HTTPException, UnprocessableEntity, NotFound,
                                 Unauthorized)
from werkzeug.routing import Map, Rule
from werkzeug.wrappers import Request, Response


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
    file_.seek(0)
    return changes


silence_re = re.compile(r'silencedetect.*silence_(start|end):\s*(\S*)')
trackgain_re = re.compile(r'replaygain.*track_gain = (\S* dB)')


def ffmpeg_audio_analyzer(playlist, fileId, ext, file_):
    command = """ffmpeg -i - -af
    replaygain,apad=pad_len=100000,silencedetect=d=0.001 -f null -""".split()

    try:
        raw_output = subprocess.check_output(command, stdin=file_,
                                             stderr=subprocess.STDOUT)
        output = text_type(raw_output, 'utf-8')
    except subprocess.CalledProcessError:
        raise UnprocessableEntity('Cannot process audio data')

    gain = trackgain_re.search(output).groups()[0]
    silence_times = re.findall(silence_re, output)
    silence_times = [(name, float(value)) for name, value in silence_times]

    # Last 'start' time is cue_out
    reversed_times = reversed(silence_times)
    cue_out = next((t[1] for t in reversed_times if t[0] == 'start'))

    # From remaining times, first 'end' time is cue_in, otherwise 0.0
    remaining_times = reversed(list(reversed_times))
    cue_in = next((t[1] for t in remaining_times if t[0] == 'end'), 0.0)

    file_.seek(0)
    return [
        MetadataChange('track_gain', gain),
        MetadataChange('cue_in', text_type(cue_in)),
        MetadataChange('cue_out', text_type(cue_out)),
    ]


DEFAULT_UPLOAD_ANALYZERS = [
    raw_file_analyzer,
    mutagen_tag_analyzer,
    ffmpeg_audio_analyzer,
]


def update_data_analyzer(playlist, fileId, ext, data):
    changes = []
    if not isinstance(data, dict):
        raise UnprocessableEntity('Invalid data format: ' +
                                  'associative array expected')
    for key, value in data.items():
        if key not in ALLOWED_METADATA_CHANGES.keys():
            raise UnprocessableEntity('Invalid data format: ' +
                                      'Key not allowed: ' + key)
        if not isinstance(value, ALLOWED_METADATA_CHANGES[key]):
            raise UnprocessableEntity(
                'Invalid data format: Type error ' +
                '(expected %s, got %s).' %
                (ALLOWED_METADATA_CHANGES[key], type(value).__name__)
            )
        changes.append(MetadataChange(key, value))
    return changes


DEFAULT_UPDATE_ANALYZERS = [update_data_analyzer]


##############
# Processors #
##############
def raw_file_processor(data_dir, playlist, fileId, ext, changes):
    path = os.path.join(data_dir, playlist, fileId + ext)
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
        else:
            raise ValueError('Change not recognized')


def index_processor(data_dir, playlist, fileId, ext, changes, json_opts={}):
    indexJson = os.path.join(data_dir, 'index.json')
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
                else:
                    raise ValueError('Change not recognized')
            f.seek(0)
            f.truncate()
            json.dump(data, f, **json_opts)
        finally:
            fcntl.lockf(f, fcntl.LOCK_UN)


TAG_KEYS = 'artist title album cue_in cue_out track_gain'.split()

mutagen.easyid3.EasyID3.RegisterTXXXKey(key='cue_in', desc='CUE_IN')
mutagen.easyid3.EasyID3.RegisterTXXXKey(key='cue_out', desc='CUE_OUT')
mutagen.easyid3.EasyID3.RegisterTXXXKey(key='track_gain',
                                        desc='REPLAYGAIN_TRACK_GAIN')


def file_tag_processor(data_dir, playlist, fileId, ext, changes):
    mutagenfile = None
    for change in changes:
        if isinstance(change, MetadataChange):
            key, value = change
            if key in TAG_KEYS:
                if mutagenfile is None:
                    path = os.path.join(data_dir, playlist, fileId + ext)
                    mutagenfile = mutagen.File(path, easy=True)

                mutagenfile[key] = text_type(value)

    if mutagenfile:
        mutagenfile.save()


def playlist_processor(data_dir, playlist, fileId, ext, changes):
    playlist_path = os.path.join(data_dir, playlist + '.m3u')
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
    raw_file_processor,   # must be first (saving file)
    file_tag_processor,   # update tags
    playlist_processor,   # update playlist file
    index_processor,      # commit file to index at last
]


############
# HTTP API #
############
class KlangbeckenAPI:

    def __init__(self,
                 data_dir,
                 secret,
                 upload_analyzers=DEFAULT_UPLOAD_ANALYZERS,
                 update_analyzers=DEFAULT_UPDATE_ANALYZERS,
                 processors=DEFAULT_PROCESSORS,
                 disable_auth=False):
        self.data_dir = data_dir
        self.secret = secret
        self.upload_analyzers = upload_analyzers
        self.update_analyzers = update_analyzers
        self.processors = processors
        self.do_auth = not disable_auth

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
            if self.do_auth and endpoint != 'login' and \
                    (session.new or 'user' not in session):
                raise Unauthorized()
            response = getattr(self, 'on_' + endpoint)(request, **values)
        except HTTPException as e:
            response = e
        return response(environ, start_response)

    def on_login(self, request):
        if request.remote_user is None:
            raise Unauthorized()

        if self.do_auth:
            user = request.environ['REMOTE_USER']
            session = request.client_session
            session['user'] = user
            response = JSONResponse({'status': 'OK', 'user': user})
            session.save_cookie(response)
        else:
            response = JSONResponse({'status': 'OK'})
        return response

    def on_logout(self, request):
        response = JSONResponse({'status': 'OK'})
        if self.do_auth:
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
            processor(self.data_dir, playlist, fileId, ext, actions)

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
        except ValueError:
            raise UnprocessableEntity('Cannot parse PUT request: ' +
                                      ' not valid JSON')

        for processor in self.processors:
            processor(self.data_dir, playlist, fileId, ext, actions)

        return JSONResponse({'status': 'OK'})

    def on_delete(self, request, playlist, fileId, ext):
        fileId = text_type(fileId)

        change = [FileDeletion()]
        for processor in self.processors:
            processor(self.data_dir, playlist, fileId, ext, change)

        return JSONResponse({'status': 'OK'})


class JSONResponse(Response):
    """
    JSON response helper
    """
    def __init__(self, data, **json_opts):
        super(JSONResponse, self).__init__(json.dumps(data, **json_opts),
                                           mimetype='text/json')


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

        # Create dir structure if needed
        self._check_and_crate_data_dir(data_full_path)

        # Application session cookie secret
        secret = ''.join(random.sample('abcdefghijklmnopqrstuvwxyz', 20))

        # Only add ffmpeg_audio_analyzer to analyzers if binary is present
        upload_analyzers = [raw_file_analyzer, mutagen_tag_analyzer]
        try:
            subprocess.check_output('ffmpeg -version'.split())
            upload_analyzers.append(ffmpeg_audio_analyzer)
        except (OSError, subprocess.CalledProcessError):  # pragma: no cover
            print('WARNING: ffmpeg binary not found. ' +
                  'No audio analysis is performed.')

        # Slightly modify processors, such that index.json is pretty printed
        processors = [
            raw_file_processor,
            functools.partial(index_processor,
                              json_opts={'indent': 2, 'sort_keys': True}),
            file_tag_processor,
            playlist_processor,
        ]

        # Create customized KlangbeckenAPI application
        api = KlangbeckenAPI(data_full_path, secret,
                             upload_analyzers=upload_analyzers,
                             processors=processors)

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

    @staticmethod
    def _check_and_crate_data_dir(data_dir):
        """
        Create local data directory structure for testing and development
        """
        for path in [data_dir] + \
                [os.path.join(data_dir, playlist) for playlist in PLAYLISTS]:
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


if __name__ == '__main__':
    # Run locally in stand-alone development mode
    from werkzeug.serving import run_simple
    run_simple('127.0.0.1', 5000, StandaloneWebApplication(),
               use_debugger=True, use_reloader=True, threaded=True)
