#!/usr/bin/python3
from __future__ import print_function, unicode_literals, division

import json
import os
from collections import Counter
from io import open
from os.path import join as pjoin

import mutagen
from werkzeug.contrib.securecookie import SecureCookie
from werkzeug.exceptions import (HTTPException, UnprocessableEntity, NotFound,
                                 Unauthorized)
from werkzeug.routing import Map, Rule
from werkzeug.utils import secure_filename, cached_property
from werkzeug.wrappers import BaseRequest, Response
from werkzeug.wsgi import wrap_file


class JSONSecureCookie(SecureCookie):
    serialization_method = json


class Request(BaseRequest):

    @cached_property
    def client_session(self):
        secret_key = os.environ['KLANGBECKEN_API_SECRET']
        return SecureCookie.load_cookie(self, secret_key=secret_key)


class KlangbeckenAPI:

    def __init__(self, stand_alone=False):
        self.data_dir = os.environ.get('KLANGBECKEN_DATA',
                                       '/var/lib/klangbecken')
        self.secret = os.environ['KLANGBECKEN_API_SECRET']
        self.url_map = Map()

        mappings = [
            ('/login/', ('GET', 'POST'), 'login'),
            ('/<any(music, jingles):category>/', ('GET',), 'list'),
            ('/<any(music, jingles):category>/<filename>', ('GET',), 'get'),
            ('/<any(music, jingles):category>/', ('POST',), 'upload'),
            ('/<any(music, jingles):category>/<filename>', ('PUT',), 'update'),
            ('/<any(music, jingles):category>/<filename>', ('DELETE',),
             'delete'),
        ]

        if stand_alone:
            # Serve html and prefix calls to api
            mappings = [('/api' + path, methods, endpoint)
                        for path, methods, endpoint in mappings]
            mappings.append(('/', ('GET',), 'static'))
            mappings.append(('/<path:path>', ('GET',), 'static'))

        for path, methods, endpoint in mappings:
            self.url_map.add(Rule(path, methods=methods, endpoint=endpoint))

    def _full_path(self, path):
        return pjoin(self.data_dir, path)

    def __call__(self, environ, start_response):
        request = Request(environ)
        adapter = self.url_map.bind_to_environ(request.environ)

        session = request.client_session
        try:
            endpoint, values = adapter.match()
            if endpoint not in ['login', 'static'] and (session.new or
                                                        'user' not in session):
                raise Unauthorized()
            response = getattr(self, 'on_' + endpoint)(request, **values)
        except HTTPException as e:
            response = e
        return response(environ, start_response)

    def on_login(self, request):
        if request.remote_user is None:
            raise Unauthorized()

        response = Response(json.dumps({'status': 'OK'}), mimetype='text/json')
        session = request.client_session
        session['user'] = request.environ['REMOTE_USER']
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
                'repeate': counter[path],
            } for (filename, path, mutagenfile) in tuples
        ]

        data = sorted(dicts, key=lambda v: v['mtime'], reverse=True)
        return Response(json.dumps(data, indent=2, sort_keys=True,
                                   ensure_ascii=True), mimetype='text/json')

    def on_get(self, request, category, filename):
        path = pjoin(category, secure_filename(filename))
        full_path = self._full_path(path)
        if not os.path.exists(full_path):
            raise NotFound()
        return Response(wrap_file(request.environ, open(full_path, 'rb')),
                        mimetype='audio/mpeg')

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

        mutagenfile = mutagen.File(self._full_path(file_path), easy=True)
        metadata = {
            'filename': filename,
            'path': file_path,
            'artist': mutagenfile.get('artist', [''])[0],
            'title': mutagenfile.get('title', [''])[0],
            'album': mutagenfile.get('album', [''])[0],
            'repeate': 1,
            'length': float(mutagenfile.info.length),
            'mtime': os.stat(self._full_path(file_path)).st_mtime,
        }
        return Response(json.dumps(metadata), mimetype='text/json')

    def on_update(self, request, category, filename):
        # FIXME: other values (artist, title)
        path = pjoin(category, secure_filename(filename))
        try:
            repeates = int(json.loads(request.data)['repeate'])
        except:
            raise UnprocessableEntity('Cannot parse PUT request')

        lines = open(self._full_path(category + '.m3u')).read().split('\n')
        with open(self._full_path(category + '.m3u'), 'w') as f:
            for line in lines:
                if line != path and line:
                    print(line, file=f)
            for i in range(repeates):
                print(path, file=f)

        return Response(json.dumps({'status': 'OK'}), mimetype='text/json')

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
        return Response(json.dumps({'status': 'OK'}), mimetype='text/json')

    def on_static(self, request, path=''):
        if path in ['', 'music', 'jingles']:
            path = 'index.html'
        path = os.path.join('app', path)

        if path.endswith('.html'):
            mimetype = 'text/html'
        elif path.endswith('.css'):
            mimetype = 'text/css'
        elif path.endswith('.js'):
            mimetype = 'text/javascript'
        else:
            mimetype = 'text/plain'

        if not os.path.isfile(path):
            raise NotFound()

        return Response(wrap_file(request.environ, open(path, 'rb')),
                        mimetype=mimetype)


if __name__ == '__main__':
    from werkzeug.serving import run_simple
    os.environ['KLANGBECKEN_DATA'] = 'data'
    os.environ['KLANGBECKEN_API_SECRET'] = os.urandom(20)
    for path in ['data', pjoin('data', 'music'), pjoin('data', 'jingles')]:
        if not os.path.isdir(path):
            os.mkdir(path)
    for path in [pjoin('data', 'music.m3u'), pjoin('data', 'jingles.m3u')]:
        if not os.path.isfile(path):
            open(path, 'a').close()

    application = KlangbeckenAPI(stand_alone=True)

    # Inject dummy remote user when testing locally
    def wrapper(environ, start_response):
        environ['REMOTE_USER'] = 'dummyuser'
        return application(environ, start_response)

    run_simple('127.0.0.1', 5000, wrapper, use_debugger=True,
               use_reloader=True, threaded=False)
else:
    application = KlangbeckenAPI()
