#!/usr/bin/python3
from __future__ import print_function, unicode_literals, division

import json
import os
import subprocess
import sys
from collections import Counter
from io import open
from os.path import join as pjoin
from xml.etree import ElementTree

import mutagen
from mutagen.easyid3 import EasyID3
from werkzeug.contrib.securecookie import SecureCookie
from werkzeug.exceptions import (HTTPException, UnprocessableEntity, NotFound,
                                 Unauthorized)
from werkzeug.routing import Map, Rule
from werkzeug.utils import secure_filename
from werkzeug.wrappers import Request, Response


PLAYLISTS = ('music', 'jingles')


############
# HTTP API #
############
class KlangbeckenAPI:

    def __init__(self):
        self.data_dir = os.environ.get('KLANGBECKEN_DATA',
                                       '/var/lib/klangbecken')
        self.secret = os.environ['KLANGBECKEN_API_SECRET']

        # register the TXXX key so that we can access it later as
        # mutagenfile['rg_track_gain']
        EasyID3.RegisterTXXXKey(key='track_gain',
                                desc='REPLAYGAIN_TRACK_GAIN')
        EasyID3.RegisterTXXXKey(key='cue_in',
                                desc='CUE_IN')
        EasyID3.RegisterTXXXKey(key='cue_out',
                                desc='CUE_OUT')

        root_url = '/<any(' + ', '.join(PLAYLISTS) + '):category>/'

        self.url_map = Map(rules=(
            Rule('/login/', methods=('GET', 'POST'), endpoint='login'),
            Rule('/logout/', methods=('POST',), endpoint='logout'),
            Rule(root_url, methods=('GET',), endpoint='list'),
            Rule(root_url, methods=('POST',), endpoint='upload'),
            Rule(root_url + '<filename>', methods=('PUT',), endpoint='update'),
            Rule(root_url + '<filename>', methods=('DELETE',),
                 endpoint='delete'),
        ))

    def _full_path(self, path):
        return pjoin(self.data_dir, path)

    def _replaygain_analysis(self, mutagenfile):
        bs1770gain_cmd = [
            "/usr/bin/bs1770gain", "--ebu", "--xml", mutagenfile.filename
        ]
        output = subprocess.check_output(bs1770gain_cmd)
        bs1770gain = ElementTree.fromstring(output)
        # lu is in bs1770gain > album > track > integrated as an attribute
        track_gain = bs1770gain.find('./album/track/integrated').attrib['lu']
        mutagenfile['track_gain'] = track_gain + ' dB'

    def _silan_analysis(self, mutagenfile):
        silan_cmd = [
            '/usr/bin/silan', '--format', 'json', mutagenfile.filename
        ]
        output = subprocess.check_output(silan_cmd)
        cue_points = json.loads(output)['sound'][0]
        mutagenfile['cue_in'] = str(cue_points[0])
        mutagenfile['cue_out'] = str(cue_points[1])

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

    def on_list(self, request, category):
        cat_dir = self._full_path(category)
        filenames = os.listdir(cat_dir)
        tuples = [(filename, os.path.join(category, filename))
                  for filename in filenames]
        tuples = [(filename, path,
                   mutagen.File(self._full_path(path), easy=True))
                  for (filename, path) in tuples
                  if os.path.isfile(self._full_path(path))
                  and path.endswith('.mp3')]
        counter = Counter(path.strip() for path in
                          open(self._full_path(category + ".m3u")).readlines())
        # FIXME: cue-points and replaygain
        dicts = [
            {
                'filename': filename,
                'path': path,
                'artist': mutagenfile.get('artist', [''])[0],
                'title': mutagenfile.get('title', [''])[0],
                'album': mutagenfile.get('album', [''])[0],
                'length': float(mutagenfile.info.length),
                'mtime': os.stat(self._full_path(path)).st_mtime,
                'repeat': counter[path],
            } for (filename, path, mutagenfile) in tuples
        ]

        data = sorted(dicts, key=lambda v: v['mtime'], reverse=True)
        return JSONResponse(data, indent=2, sort_keys=True, ensure_ascii=True)

    def on_upload(self, request, category):
        file = request.files['files']

        if not file:
            raise UnprocessableEntity()

        filename = secure_filename(file.filename)
        # filename = gen_file_name(filename) # FIXME: check duplicate filenames
        # mimetype = file.content_type

        if not file.filename.endswith('.mp3'):
            raise UnprocessableEntity('Filetype not allowed ')

        # save file to disk
        file_path = pjoin(category, filename)
        file.save(self._full_path(file_path))
        with open(self._full_path(category + '.m3u'), 'a') as f:
            print(file_path, file=f)

        # FIXME: silan and replaygain
        # gst-launch-1.0 -t filesrc location=02_Prada.mp3 ! decodebin !
        #  audioconvert ! audioresample ! rganalysis ! fakesink

        mutagenfile = mutagen.File(self._full_path(file_path), easy=True)
        self._replaygain_analysis(mutagenfile)
        self._silan_analysis(mutagenfile)
        mutagenfile.save()
        metadata = {
            'filename': filename,
            'path': file_path,
            'artist': mutagenfile.get('artist', [''])[0],
            'title': mutagenfile.get('title', [''])[0],
            'album': mutagenfile.get('album', [''])[0],
            'repeat': 1,
            'length': float(mutagenfile.info.length),
            'mtime': os.stat(self._full_path(file_path)).st_mtime,
        }
        return JSONResponse(metadata)

    def on_update(self, request, category, filename):
        # FIXME: other values (artist, title)
        path = pjoin(category, secure_filename(filename))
        try:
            data = json.loads(request.data)
            repeats = int(data['repeat'])
        except:  # noqa: E722
            raise UnprocessableEntity('Cannot parse PUT request')

        lines = open(self._full_path(category + '.m3u')).read().split('\n')
        with open(self._full_path(category + '.m3u'), 'w') as f:
            for line in lines:
                if line != path and line:
                    print(line, file=f)
            for i in range(repeats):
                print(path, file=f)

        return JSONResponse({'status': 'OK'})

    def on_delete(self, request, category, filename):
        path = pjoin(category, secure_filename(filename))
        if not os.path.exists(self._full_path(path)):
            raise NotFound()
        os.remove(self._full_path(path))
        lines = open(self._full_path(category + '.m3u')).read().split('\n')
        with open(self._full_path(category + '.m3u'), 'w') as f:
            for line in lines:
                if line != path and line:
                    print(line, file=f)
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
class StandaloneKlangbecken:
    """
    Stand-alone Klangbecken WSGI application for testing and development.

    * Serves static files from the dist directory
    * Serves data files from the data directory
    * Relays API calls to the KlangbeckenAPI instance

    Authentication is simulated.
    """

    def __init__(self):
        import random
        from werkzeug.wsgi import DispatcherMiddleware, SharedDataMiddleware

        # Assemble useful paths
        current_path = os.path.dirname(os.path.realpath(__file__))
        data_full_path = pjoin(current_path, 'data')
        dist_dir = open(pjoin(current_path, '.dist_dir')).read().strip()
        dist_full_path = pjoin(current_path, dist_dir)

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
        app = DispatcherMiddleware(app, {'/api': KlangbeckenAPI()})

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
    data_dir = pjoin(os.path.dirname(os.path.abspath(__file__)), 'data')
    for path in [data_dir] + [pjoin(data_dir, d) for d in PLAYLISTS]:
        if not os.path.isdir(path):
            os.mkdir(path)
    for path in [pjoin(data_dir, d + '.m3u') for d in PLAYLISTS]:
        if not os.path.isfile(path):
            open(path, 'a').close()


def main():
    """
    Run server or importer locally
    """
    from werkzeug.serving import run_simple

    _check_and_crate_data_dir()

    if len(sys.argv) == 1:
        application = StandaloneKlangbecken()
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
