#!/usr/bin/python3
import json
import os
from collections import Counter

import mutagen
from werkzeug.exceptions import HTTPException, UnprocessableEntity, NotFound
from werkzeug.routing import Map, Rule
from werkzeug.utils import secure_filename
from werkzeug.wrappers import Request, Response
from werkzeug.wsgi import wrap_file


class KlangbeckenAPI:

    def __init__(self, stand_alone=False):
        if stand_alone:
            self.data_dir = os.environ.get('KLANGBECKEN_DATA', '..')
        else:
            self.data_dir = os.environ.get('KLANGBECKEN_DATA',
                                           '/var/lib/klangbecken')

        mappings = [
            ('/<any(music, jingles):category>/', 'GET', 'list'),
            ('/<any(music, jingles):category>/<filename>', 'GET', 'get'),
            ('/<any(music, jingles):category>/', 'POST', 'upload'),
            ('/<any(music, jingles):category>/<filename>', 'PUT', 'update'),
            ('/<any(music, jingles):category>/<filename>', 'DELETE', 'delete'),
        ]

        if stand_alone:
            # Serve html and prefix calls to api
            mappings = ['/api' + path, method, endpoint
                        for path, method, endpoint in mappings]
            mappings.insert(0, ('/<any("", music, jingles, settings):page>',
                                'GET', 'app')

        for path, method, endpoint in [:
            self.url_map.add(Rule(path, methods=(method,), endpoint=endpoint))


    def __call__(self, environ, start_response):
        request = Request(environ)
        adapter = self.url_map.bind_to_environ(request.environ)
        try:
            endpoint, values = adapter.match()
            response = getattr(self, 'on_' + endpoint)(request, **values)
        except HTTPException as e:
            response = e
        return response(environ, start_response)

    def on_app(self, request, page):
        del page # not used (client side routing)
        return Response(wrap_file(request.environ, open('app/index.html')),
                        mimetype='text/html')

    def on_list(self, request, category):
        cat_dir = os.path.join(self.data_dir, category)
        filenames = os.listdir(cat_dir)
        tuples = [(filename, os.path.join(cat_dir, filename))
                  for filename in filenames]
        tuples = [(filename, path, mutagen.File(path, easy=True))
                  for (filename, path) in tuples
                  if os.path.isfile(path) and path.endswith('.mp3')]
        counter = Counter(open(category + ".m3u").read().split())
        # FIXME: cue-points and replaygain
        dicts = [
            {
                'filename': filename,
                'path': path,
                'artist': mutagenfile.get('artist', [''])[0],
                'title': mutagenfile.get('title', [''])[0],
                'album': mutagenfile.get('album', [''])[0],
                'length': float(mutagenfile.info.length),
                'mtime': os.stat(path).st_mtime,
                'repeate': counter[path],
            } for (filename, path, mutagenfile) in tuples
        ]

        data = sorted(dicts, key=lambda v: v['mtime'], reverse=True)
        return Response(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True),
                        mimetype='text/json')

    def on_get(self, request, category, filename):
        path = os.path.join(category, secure_filename(filename))
        if not os.path.exists(path):
            raise NotFound()
        return Response(wrap_file(request.environ, open(path, 'rb')),
                        mimetype='audio/mpeg')

    def on_upload(self, request, category):
        file = request.files['files']

        if not file:
            raise UnprocessableEntity()

        filename = secure_filename(file.filename)
        #filename = gen_file_name(filename) # FIXME: check for duplicate filenames
        # mimetype = file.content_type

        if not file.filename.endswith('.mp3'):
            raise UnprocessableEntity('Filetype not allowed ')

        # save file to disk
        uploaded_file_path = os.path.join(self.data_dir ,category, filename)
        file.save(uploaded_file_path)
        with open(category + '.m3u', 'a') as f:
            print(uploaded_file_path, file=f)

        # FIXME: silan and replaygain

        mutagenfile = mutagen.File(uploaded_file_path, easy=True)
        metadata = {
            'filename': filename,
            'path': uploaded_file_path,
            'artist': mutagenfile.get('artist', [''])[0],
            'title': mutagenfile.get('title', [''])[0],
            'album': mutagenfile.get('album', [''])[0],
            'repeat': 1,
            'length': float(mutagenfile.info.length),
            'mtime': os.stat(uploaded_file_path).st_mtime,
        }
        return Response(json.dumps(metadata), mimetype='text/json')

    def on_update(self, request, category, filename):
        # FIXME: other values (artist, title)
        path = os.path.join(self.data_dir, category, secure_filename(filename))
        try:
            repeates = int(json.loads(str(request.data, 'UTF-8'))['repeate'])
        except:
            raise UnprocessableEntity('Cannot parse PUT request')

        lines = open(category + '.m3u').read().split('\n')
        with open(category + '.m3u', 'w') as f:
            for line in lines:
                if line != path and line:
                    print(line, file=f)
            for i in range(repeates):
                print(path, file=f)

        return Response(json.dumps({'status': 'OK'}), mimetype='text/json')

    def on_delete(self, request, category, filename):
        path = os.path.join(self.data_dir, category, secure_filename(filename))
        if not os.path.exists(path):
            raise NotFound()
        os.remove(path)
        lines = open(category + '.m3u').read().split('\n')
        with open(category + '.m3u', 'w') as f:
            for line in lines:
                if line != path and line:
                    print(line, file=f)
        return Response(json.dumps({'status': 'OK'}), mimetype='text/json')

    def on_static(self, request, folder, filename):
        path = os.path.join(folder, secure_filename(filename))
        if path.endswith('.css'):
            mimetype = 'text/css'
        elif path.endswith('.js'):
            mimetype = 'text/javascript'
        else:
            mimetype = 'text/plain'

        if not os.path.isfile(path):
            raise NotFound()

        return Response(wrap_file(request.environ, open(path, 'rb')), mimetype=mimetype)

if __name__ == '__main__':
    from werkzeug.serving import run_simple
    app = KlangbeckenAPI(stand_alone=True)
    run_simple('127.0.0.1', 5000, app, use_debugger=True, use_reloader=True,
               threaded=True)
else:
    application = KlangbeckenAPI()
