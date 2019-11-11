#!/usr/bin/env python
##############################################################################
# klangbecken_api.py - Klangbecken API                                       #
##############################################################################
#
# Copyright 2017-2018 Radio Bern RaBe, Switzerland, https://rabe.ch
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

from __future__ import print_function, unicode_literals, division

import collections
import contextlib
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
import time
import uuid

import mutagen
import mutagen.easyid3
import mutagen.flac
import mutagen.mp3
import mutagen.oggvorbis

from six import text_type
from six.moves import input

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

ALLOWED_METADATA = {
    'id': (text_type, r'^[a-z0-9]{8}-([a-z0-9]{4}-){3}[a-z0-9]{12}$'),
    'ext': (text_type, lambda ext: ext in SUPPORTED_FILE_TYPES.keys()),
    'playlist': (text_type, lambda pl: pl in PLAYLISTS),
    'original_filename': text_type,
    'import_timestamp': float,
    'weight': (int, lambda c: c >= 0),

    'artist': text_type,
    'title': text_type,
    'album': text_type,
    'length': (float, lambda n: n >= 0.0),

    'track_gain': (text_type, r'^[+-]?[0-9]*(\.[0-9]*) dB$'),
    'cue_in':  (float, lambda n: n >= 0.0),
    'cue_out': (float, lambda n: n >= 0.0),

    'play_count': (int, lambda n: n >= 0),
}

UPDATE_KEYS = 'artist title album weight'.split()
TAG_KEYS = ('artist title album cue_in cue_out track_gain '
            'original_filename import_timestamp').split()

####################
# Action-"Classes" #
####################
FileAddition = collections.namedtuple('FileAddition', ('file'))
MetadataChange = collections.namedtuple('MetadataChange', ('key', 'value'))
FileDeletion = collections.namedtuple('FileDeletion', ())


#############
# Analyzers #
#############
def raw_file_analyzer(playlist, fileId, ext, file_):
    if not file_:
        raise UnprocessableEntity('No File found')

    if ext not in SUPPORTED_FILE_TYPES.keys():
        raise UnprocessableEntity('Unsupported file extension: %s' % ext)

    # Be compatible with werkzeug.datastructures.FileStorage and plain files
    filename = file_.filename if hasattr(file_, 'filename') else file_.name

    return [
        FileAddition(file_),
        MetadataChange('id', fileId),
        MetadataChange('ext', ext),
        MetadataChange('playlist', playlist),
        MetadataChange('original_filename', filename),
        MetadataChange('import_timestamp', time.time()),
        MetadataChange('weight', 1),
        MetadataChange('play_count', 0),
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
        # Non-ASCII characters can safely be ignored
        output = text_type(raw_output, 'ascii', errors='ignore')
    except subprocess.CalledProcessError:
        raise UnprocessableEntity('Cannot process audio data')

    gain = trackgain_re.search(output).groups()[0]
    silence_times = re.findall(silence_re, output)
    silence_times = [(name, float(value)) for name, value in silence_times]

    # Last 'start' time is cue_out
    reversed_times = reversed(silence_times)
    cue_out = next((t[1] for t in reversed_times
                    if t[0] == 'start'))                # pragma: no cover

    if -0.05 < cue_out < 0.0:  # pragma: no cover
        cue_out = 0.0

    # From remaining times, first 'end' time is cue_in, otherwise 0.0
    remaining_times = reversed(list(reversed_times))
    cue_in = next((t[1] for t in remaining_times if t[0] == 'end'), 0.0)

    if -0.05 < cue_in < 0.0:  # pragma: no cover
        cue_in = 0.0

    file_.seek(0)
    return [
        MetadataChange('track_gain', gain),
        MetadataChange('cue_in', cue_in),
        MetadataChange('cue_out', cue_out),
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
        if key not in UPDATE_KEYS:
            raise UnprocessableEntity('Invalid data format: ' +
                                      'Key not allowed: ' + key)
        changes.append(MetadataChange(key, value))
    return changes


DEFAULT_UPDATE_ANALYZERS = [
    update_data_analyzer
]


##############
# Processors #
##############
def check_processor(data_dir, playlist, fileId, ext, changes):
    for change in changes:
        if isinstance(change, MetadataChange):
            key, val = change

            if key not in ALLOWED_METADATA.keys():
                raise UnprocessableEntity('Invalid metadata key: {}'
                                          .format(key))

            checks = ALLOWED_METADATA[key]
            if not isinstance(checks, (list, tuple)):
                checks = (checks,)

            for check in checks:
                if isinstance(check, type):
                    if not isinstance(val, check):
                        raise UnprocessableEntity(
                            'Invalid data format for "{}": Type error '
                            '(expected {}, got {}).'
                            .format(key, check.__name__, type(val).__name__)
                        )
                elif callable(check):
                    if not check(val):
                        raise UnprocessableEntity(
                            'Invalid data format for "{}": Check failed '
                            '(value: "{}").'
                            .format(key, val)
                        )
                elif isinstance(check, text_type):
                    if re.match(check, val) is None:
                        raise UnprocessableEntity(
                            'Invalid data format for "{}": Regex check failed '
                            '(value: "{}", regex: "{}").'
                            .format(key, val, check)
                        )
                else:
                    raise NotImplementedError()
        elif isinstance(change, (FileAddition, FileDeletion)):
            pass
        else:
            raise ValueError('Invalid action class')


def filter_duplicates_processor(data_dir, playlist, file_id, ext, changes):
    with open(os.path.join(data_dir, 'index.json')) as f:
        data = json.load(f)

    addition = [c for c in changes if isinstance(c, FileAddition)]
    if addition:
        changes = [c for c in changes if isinstance(c, MetadataChange)]

        fname = [c.value for c in changes if c.key == 'original_filename'][0]
        title = [c.value for c in changes if c.key == 'title'][0]
        artist = [c.value for c in changes if c.key == 'artist'][0]

        for entry in data.values():
            if (entry['original_filename'] == fname and
                    entry['artist'] == artist and
                    entry['title'] == title):
                raise UnprocessableEntity('Duplicate file entry:\n' +
                                          artist + ' - ' + title +
                                          ' (' + fname + ')')


def raw_file_processor(data_dir, playlist, fileId, ext, changes):
    path = os.path.join(data_dir, playlist, fileId + ext)
    for change in changes:
        if isinstance(change, FileAddition):
            file_ = change.file
            if isinstance(file_, text_type):
                shutil.copy(file_, path)
            else:
                with open(path, 'wb') as dest:
                    shutil.copyfileobj(file_, dest)
        elif isinstance(change, FileDeletion):
            if not os.path.isfile(path):
                raise NotFound()
            os.remove(path)
        elif isinstance(change, MetadataChange):
            if not os.path.isfile(path):
                raise NotFound()
        else:
            raise ValueError('Invalid action class')


def index_processor(data_dir, playlist, fileId, ext, changes, json_opts={}):
    with locked_open(os.path.join(data_dir, 'index.json')) as f:
        data = json.load(f)
        for change in changes:
            if isinstance(change, FileAddition):
                if fileId in data:
                    raise UnprocessableEntity('Duplicate file ID: ' + fileId)
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


mutagen.easyid3.EasyID3.RegisterTXXXKey(key='cue_in', desc='CUE_IN')
mutagen.easyid3.EasyID3.RegisterTXXXKey(key='cue_out', desc='CUE_OUT')
mutagen.easyid3.EasyID3.RegisterTXXXKey(key='track_gain',
                                        desc='REPLAYGAIN_TRACK_GAIN')
mutagen.easyid3.EasyID3.RegisterTXXXKey(key='original_filename',
                                        desc='ORIGINAL_FILENAME')
mutagen.easyid3.EasyID3.RegisterTXXXKey(key='import_timestamp',
                                        desc='IMPORT_TIMESTAMP')


def file_tag_processor(data_dir, playlist, fileId, ext, changes):
    mutagenfile = None
    for change in changes:
        if isinstance(change, MetadataChange):
            key, value = change
            if key in TAG_KEYS:
                if mutagenfile is None:
                    path = os.path.join(data_dir, playlist, fileId + ext)
                    FileType = SUPPORTED_FILE_TYPES[ext]
                    mutagenfile = FileType(path)

                mutagenfile[key] = text_type(value)

    if mutagenfile:
        with locked_open(path):
            mutagenfile.save()


def playlist_processor(data_dir, playlist, fileId, ext, changes):
    playlist_path = os.path.join(data_dir, playlist + '.m3u')
    for change in changes:
        if isinstance(change, FileDeletion):
            with locked_open(playlist_path) as f:
                lines = (s.strip() for s in f.readlines() if s != '\n')
                f.seek(0)
                f.truncate()
                for line in lines:
                    if not line.endswith(os.path.join(playlist, fileId + ext)):
                        print(line, file=f)
        elif isinstance(change, MetadataChange) and change.key == 'weight':
            with locked_open(playlist_path) as f:
                lines = (s.strip() for s in f.readlines() if s != '\n')
                lines = [s for s in lines
                         if s and not s.endswith(fileId + ext)]

                weight = change.value
                lines.extend([os.path.join(playlist, fileId + ext)] * weight)
                random.shuffle(lines)  # TODO: custom shuffling?
                f.seek(0)
                f.truncate()
                for line in lines:
                    print(line, file=f)


DEFAULT_PROCESSORS = [
    check_processor,      # type and contract check changes
    filter_duplicates_processor,
    raw_file_processor,   # save file
    file_tag_processor,   # update tags
    playlist_processor,   # update playlist file
    index_processor,      # commit file to index at last
]


def playnext_processor(data_dir, data):
    if not isinstance(data, dict):
        raise UnprocessableEntity('Invalid data format: ' +
                                  'associative array expected')
    if 'file' not in data:
        raise UnprocessableEntity('Invalid data format: ' +
                                  'Key "file" not found')

    filename = data['file']
    filename_re = r'^({})/([^/.]+)({})$' \
        .format('|'.join(PLAYLISTS), '|'.join(SUPPORTED_FILE_TYPES.keys()))
    if not re.match(filename_re, filename):
        raise UnprocessableEntity('Invalid file path format')

    path = os.path.join(data_dir, filename)
    if not os.path.isfile(path):
        raise NotFound()

    with locked_open(os.path.join(data_dir, 'prio.m3u')) as f:
        f.seek(0)
        f.truncate()
        print(filename, file=f)


# Locking Helper

_locks = {}


@contextlib.contextmanager
def locked_open(path):
    if path not in _locks:
        _locks[path] = threading.Lock()
    with _locks[path]:   # Prevent more than one thread accessing the file
        with open(path, 'r+') as f:
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
            Rule('/playnext/', methods=('POST',), endpoint='play_next')
        ))

    def __call__(self, environ, start_response):
        adapter = self.url_map.bind_to_environ(environ)
        request = Request(environ)
        session = JSONSecureCookie.load_cookie(request, secret_key=self.secret)
        request.client_session = session
        try:
            endpoint, values = adapter.match()
            if self.do_auth and endpoint != 'login' and \
                    (session.new or 'user' not in session):
                raise Unauthorized()
            response = getattr(self, 'on_' + endpoint)(request, **values)
        except HTTPException as e:
            response = JSONResponse({'code': e.code,
                                     'name': e.name,
                                     'description': e.description},
                                    status=e.code)
        return response(environ, start_response)

    def on_login(self, request):
        if self.do_auth:
            session = request.client_session

            if request.remote_user is not None:  # Auth successful
                user = request.environ['REMOTE_USER']
            elif 'user' in session:              # Already logged in
                user = session['user']
            else:                                # None of both
                raise Unauthorized()

            session['user'] = user

            response = JSONResponse({'status': 'OK', 'user': user})
            session.save_cookie(
                response,
                httponly=True,
                expires=datetime.datetime.now() + datetime.timedelta(days=7),
                max_age=7 * 24 * 60 * 60  # one week
            )
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

        try:
            uploadFile = request.files['file']

            ext = os.path.splitext(uploadFile.filename)[1].lower()
            fileId = text_type(uuid.uuid4())   # Generate new file id

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

    def on_play_next(self, request):
        try:
            data = json.loads(text_type(request.data, 'utf-8'))
            playnext_processor(self.data_dir, data)

        except (UnicodeDecodeError, TypeError):
            raise UnprocessableEntity('Cannot parse PUT request: ' +
                                      ' not valid UTF-8 data')
        except ValueError:
            raise UnprocessableEntity('Cannot parse PUT request: ' +
                                      ' not valid JSON')

        return JSONResponse({'status': 'OK'})


class JSONResponse(Response):
    """
    JSON response helper
    """
    def __init__(self, data, status=200, **json_opts):
        super(JSONResponse, self).__init__(json.dumps(data, **json_opts),
                                           status=status, mimetype='text/json')


class JSONSerializer:
    @staticmethod
    def dumps(obj):
        # UTF-8 encoding is default in Python 3+
        return json.dumps(obj).encode('utf-8')

    @staticmethod
    def loads(serialized):
        # UTF-8 encoding is default in Python 3+
        return json.loads(text_type(serialized, 'utf-8'))


class JSONSecureCookie(SecureCookie):
    serialization_method = JSONSerializer


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
        from werkzeug.middleware.dispatcher import DispatcherMiddleware
        from werkzeug.middleware.shared_data import SharedDataMiddleware

        # Assemble useful paths
        current_path = os.path.dirname(os.path.realpath(__file__))
        data_full_path = data_path or os.path.join(current_path, 'data')
        with open(os.path.join(current_path, '.dist_dir')) as f:
            dist_dir = f.read().strip()
        dist_full_path = os.path.join(current_path, dist_dir)

        # Create dir structure if needed
        check_and_crate_data_dir(data_full_path)

        # Application session cookie secret
        secret = ''.join(random.sample('abcdefghijklmnopqrstuvwxyz', 20))

        # Only add ffmpeg_audio_analyzer to analyzers if binary is present
        upload_analyzers = [raw_file_analyzer, mutagen_tag_analyzer]
        try:
            subprocess.check_output('ffmpeg -version'.split())
            upload_analyzers.append(ffmpeg_audio_analyzer)
        except (OSError, subprocess.CalledProcessError):  # pragma: no cover
            print('WARNING: ffmpeg binary not found. ' +
                  'No audio analysis is performed.', file=sys.stderr)

        # Slightly modify processors, such that index.json is pretty printed
        processors = [
            check_processor,
            raw_file_processor,
            filter_duplicates_processor,
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


def check_and_crate_data_dir(data_dir, create=True):
    """
    Create local data directory structure for testing and development
    """
    for path in [data_dir] + \
            [os.path.join(data_dir, playlist) for playlist in PLAYLISTS]:
        if not os.path.isdir(path):
            if create:
                os.mkdir(path)
            else:
                raise Exception('Directory "{}" does not exist'
                                .format(path))
    for path in [os.path.join(data_dir, d + '.m3u') for d in
                 PLAYLISTS + ('prio',)]:
        if not os.path.isfile(path):
            if create:
                with open(path, 'a'):
                    pass
            else:
                raise Exception('Playlist "{}" does not exist'
                                .format(path))
    path = os.path.join(data_dir, 'index.json')
    if not os.path.isfile(path):
        if create:
            with open(path, 'w') as f:
                f.write('{}')
        else:
            raise Exception('File "index.json" does not exist')


################
# Entry points #
################
def import_files(interactive=True):
    """
    Entry point for import script
    """
    def err(*args):
        print(*(arg if isinstance(arg, text_type) else text_type(arg, 'utf-8')
                for arg in args), file=sys.stderr)

    try:
        def _convert(x):   # pragma: no cover
            if isinstance(x, text_type):
                return x
            else:
                return text_type(x, sys.stdin.encoding, 'ignore')

        args = [_convert(arg) for arg in sys.argv]
        data_dir = args[1]
        playlist = args[2]
        files = args[3:]
        files[0]
    except IndexError:
        err('Usage:\npython import_files DATA_DIR PLAYLIST FILE...')
        sys.exit(1)

    try:
        check_and_crate_data_dir(data_dir, False)
    except Exception as e:
        err('ERROR: Problem with data directory.', text_type(e))
        sys.exit(1)

    if playlist not in PLAYLISTS:
        err('ERROR: Invalid playlist name: {}'.format(playlist))
        sys.exit(1)

    analysis_data = []
    for filename in files:
        try:
            analysis_data.append(
                _analyze_one_file(data_dir, playlist, filename)
            )
        except UnprocessableEntity as e:
            err('WARNING: File cannot be analyzed: ' + filename)
            err('WARNING: ' + e.description if hasattr(e, 'description')
                else text_type(e))
        except Exception as e:  # pragma: no cover
            err('WARNING: Unknown error when analyzing file: ' + filename)
            err('WARNING: ' + e.description if hasattr(e, 'description')
                else text_type(e))

    print('Successfully analyzed {} of {} files.'.format(len(analysis_data),
                                                         len(files)))
    count = 0
    print('Start import now? [y/N]', end=' ')
    if not interactive or input().strip().lower() == 'y':
        for filename, fileId, ext, actions in analysis_data:
            try:
                for processor in DEFAULT_PROCESSORS:
                    processor(data_dir, playlist, fileId, ext, actions)
                count += 1
            except Exception as e:  # pragma: no cover
                err('WARNING: File cannot be imported: ' + filename,
                    e.description if hasattr(e, 'description')
                    else text_type(e))

    print('Successfully imported {} of {} files.'.format(count, len(files)))
    sys.exit(1 if count < len(files) else 0)


def _analyze_one_file(data_dir, playlist, filename):
    if not os.path.exists(filename):
        raise UnprocessableEntity('File not found: ' + filename)

    ext = os.path.splitext(filename)[1].lower()
    if ext not in SUPPORTED_FILE_TYPES.keys():
        raise UnprocessableEntity('File extension not supported: ' + ext)

    with open(filename, 'rb') as importFile:
        fileId = text_type(uuid.uuid4())
        actions = []
        for analyzer in DEFAULT_UPLOAD_ANALYZERS:
            actions += analyzer(playlist, fileId, ext, importFile)

        actions.append(MetadataChange('original_filename',
                                      os.path.basename(filename)))
        actions.append(MetadataChange('import_timestamp',
                                      os.stat(filename).st_mtime))

        actions[0] = FileAddition(filename)
    return (filename, fileId, ext, actions)


def fsck():
    """
    Entry point for fsck script
    """
    id = None

    def err(*args):
        if id is not None:
            print('ERROR when processing', id, file=sys.stderr)
        print(*args, file=sys.stderr)
        err.count += 1
    err.count = 0

    try:
        data_dir = sys.argv[1]
    except IndexError:
        err('Usage:\npython fsck.py DATA_DIR')
        sys.exit(1)

    try:
        check_and_crate_data_dir(data_dir, False)
    except Exception as e:
        err('ERROR: Problem with data directory.', text_type(e))
        sys.exit(1)

    with locked_open(os.path.join(data_dir, 'index.json')) as f:
        try:
            data = json.load(f)
        except ValueError as e:
            err('ERROR: Cannot read index.json', text_type(e))
            sys.exit(1)  # abort

        files = set()
        playlist_counts = collections.Counter()
        for playlist in PLAYLISTS:
            files.update(os.path.join(playlist, entry) for entry in
                         os.listdir(os.path.join(data_dir, playlist)))
            with open(os.path.join(data_dir, playlist + '.m3u')) as f1:
                playlist_counts.update(line.strip() for line in
                                       f1.readlines())
        for id, entries in data.items():
            keys = set(entries.keys())
            missing = set(ALLOWED_METADATA.keys()) - keys
            if missing:
                err('ERROR: missing entries:', ', '.join(missing))
                continue   # cannot continue with missing entries
            too_many = keys - set(ALLOWED_METADATA.keys())
            if too_many:
                err('ERROR: too many entries:', ', '.join(too_many))
            try:
                check_processor(data_dir, entries['playlist'],
                                entries['id'], entries['ext'],
                                (MetadataChange(key, val)
                                    for key, val in entries.items()))
            except UnprocessableEntity as e:
                err('ERROR:', text_type(e))
            if id != entries['id']:
                err('ERROR: Id missmatch', id, entries['id'])
            if entries['cue_in'] > entries['cue_out']:
                err('ERROR: cue_in larger than cue_out',
                    text_type(entries['cue_in']),
                    text_type(entries['cue_out']))
            if entries['cue_out'] > entries['length']:
                err('ERROR: cue_out larger than length',
                    text_type(entries['cue_out']),
                    text_type(entries['length']))
            file_path = os.path.join(entries['playlist'],
                                     entries['id'] + entries['ext'])
            file_full_path = os.path.join(data_dir, file_path)
            if not os.path.isfile(file_full_path):
                err('ERROR: file does not exist:', file_full_path)
            else:
                files.remove(file_path)
                FileType = SUPPORTED_FILE_TYPES[entries['ext']]
                mutagenfile = FileType(file_full_path)
                for key in TAG_KEYS:
                    tag_value = mutagenfile.get(key, [''])[0]
                    if text_type(entries[key]) != tag_value:
                        err('ERROR: Tag value mismatch "{}": {} != {}'
                            .format(key, entries[key], tag_value))

                count = playlist_counts[file_path]
                del playlist_counts[file_path]
                if count != entries['weight']:
                    err('ERROR: Playlist weight mismatch: {} != {}'
                        .format(entries['weight'], count))

        if files:
            err('ERROR: Dangling files:', ', '.join(files))
        if playlist_counts:
            err('ERROR: Dangling playlist entry:',
                ', '.join(playlist_counts.keys()))

    sys.exit(1 if err.count else 0)


if __name__ == '__main__':
    # Run locally in stand-alone development mode
    from werkzeug.serving import run_simple
    run_simple('127.0.0.1', 5000, StandaloneWebApplication(),
               use_debugger=True, use_reloader=True, threaded=True)
