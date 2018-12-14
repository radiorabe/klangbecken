# -*- coding: utf-8 -*-
from __future__ import unicode_literals, print_function

import contextlib
import io
import json
import mock
import os
import shutil
import six
import sys
import tempfile
import unittest
import uuid

from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import NotFound, UnprocessableEntity
from werkzeug.test import Client
from werkzeug.wrappers import BaseResponse


@contextlib.contextmanager
def capture(command, *args, **kwargs):

    out, sys.stdout = sys.stdout, io.StringIO()
    try:
        command(*args, **kwargs)
        sys.stdout.seek(0)
        yield sys.stdout.read()
    finally:
        sys.stdout = out


class WSGIAppTest(unittest.TestCase):
    def test_application(self):
        from klangbecken_api import KlangbeckenAPI
        application = KlangbeckenAPI('inexistent_dir', 'secret')
        self.assertTrue(callable(application))


class APITestCase(unittest.TestCase):
    def setUp(self):
        from klangbecken_api import (KlangbeckenAPI, FileAddition,
                                     MetadataChange)

        self.upload_analyzer = mock.Mock(return_value=[
            FileAddition('testfile'),
            MetadataChange('testkey', 'testvalue')
        ])
        self.update_analyzer = mock.Mock(return_value=['UpdateChange'])
        self.processor = mock.MagicMock()

        app = KlangbeckenAPI(
            'data_dir',
            'secret',
            upload_analyzers=[self.upload_analyzer],
            update_analyzers=[self.update_analyzer],
            processors=[self.processor],
            disable_auth=True,
        )
        self.client = Client(app, BaseResponse)

    def testUrls(self):
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 404)
        resp = self.client.get('/login/')
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post('/login/')
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post('/logout/')
        self.assertEqual(resp.status_code, 200)
        resp = self.client.get('/music/')
        self.assertEqual(resp.status_code, 405)
        resp = self.client.get('/jingles/')
        self.assertEqual(resp.status_code, 405)
        resp = self.client.get('/nonexistant/')
        self.assertEqual(resp.status_code, 404)
        resp = self.client.get('/öäü/')
        self.assertEqual(resp.status_code, 404)
        resp = self.client.post('/jingles')
        self.assertEqual(resp.status_code, 301)
        resp = self.client.post('/music/')
        self.assertEqual(resp.status_code, 422)
        resp = self.client.post('/jingles/something')
        self.assertEqual(resp.status_code, 404)
        resp = self.client.put('/music/')
        self.assertEqual(resp.status_code, 405)
        resp = self.client.put('/jingles/something')
        self.assertEqual(resp.status_code, 404)
        resp = self.client.put('/jingles/something.mp3')
        self.assertEqual(resp.status_code, 404)
        resp = self.client.put('/music/' + str(uuid.uuid1()))
        self.assertEqual(resp.status_code, 404)
        resp = self.client.put('/music/' + str(uuid.uuid1()) + '.mp3')
        self.assertEqual(resp.status_code, 422)
        resp = self.client.put('/jingles/' + str(uuid.uuid1()) + '.ogg')
        self.assertEqual(resp.status_code, 422)
        resp = self.client.put('/music/' + str(uuid.uuid1()) + '.flac')
        self.assertEqual(resp.status_code, 422)
        resp = self.client.put('/jingles/' + str(uuid.uuid1()) + '.ttt')
        self.assertEqual(resp.status_code, 404)
        resp = self.client.delete('/music/')
        self.assertEqual(resp.status_code, 405)
        resp = self.client.delete('/jingles/something')
        self.assertEqual(resp.status_code, 404)
        resp = self.client.delete('/jingles/something.mp3')
        self.assertEqual(resp.status_code, 404)
        resp = self.client.delete('/music/' + str(uuid.uuid1()))
        self.assertEqual(resp.status_code, 404)
        resp = self.client.delete('/jingles/' + str(uuid.uuid1()) + '.mp3')
        self.assertEqual(resp.status_code, 200)
        resp = self.client.delete('/music/' + str(uuid.uuid1()) + '.ogg')
        self.assertEqual(resp.status_code, 200)
        resp = self.client.delete('/jingles/' + str(uuid.uuid1()) + '.flac')
        self.assertEqual(resp.status_code, 200)
        resp = self.client.delete('/music/' + str(uuid.uuid1()) + '.ttt')
        self.assertEqual(resp.status_code, 404)

    def testUpload(self):
        from klangbecken_api import FileAddition, MetadataChange

        # Correct upload
        resp = self.client.post(
            '/music/',
            data={'file': (io.BytesIO(b'testcontent'), 'test.mp3')},
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(six.text_type(resp.data, 'ascii'))
        fileId = list(data.keys())[0]
        self.assertEqual(fileId, six.text_type(uuid.UUID(fileId)))
        self.assertEqual(list(data.values())[0], {'testkey': 'testvalue'})
        self.update_analyzer.assert_not_called()
        self.upload_analyzer.assert_called_once()
        args = self.upload_analyzer.call_args[0]
        self.assertEqual(args[0], 'music')
        self.assertEqual(args[1], fileId)
        self.assertEqual(args[2], '.mp3')
        self.assertTrue(isinstance(args[3], FileStorage))
        self.assertEqual(args[3].filename, 'test.mp3')
        self.assertEqual(args[3].mimetype, 'audio/mpeg')
        self.assertTrue(args[3].closed)

        self.processor.assert_called_once_with(
            'data_dir', 'music', fileId, '.mp3',
            [FileAddition('testfile'), MetadataChange('testkey', 'testvalue')]
        )

        self.upload_analyzer.reset_mock()
        self.processor.reset_mock()

        # Wrong attribute name
        resp = self.client.post(
            '/music/',
            data={'not-file': (io.BytesIO(b'testcontent'), 'test.mp3')},
        )
        self.assertEqual(resp.status_code, 422)
        self.assertTrue(b'No attribute named \'file\' found' in resp.data)
        self.update_analyzer.assert_not_called()
        self.upload_analyzer.assert_not_called()
        self.processor.assert_not_called()

        # File as normal text attribute
        resp = self.client.post(
            '/music/',
            data={'file': 'testcontent', 'filename': 'test.mp3'},
        )
        self.assertEqual(resp.status_code, 422)
        self.assertTrue(b'No attribute named \'file\' found' in resp.data)
        self.update_analyzer.assert_not_called()
        self.upload_analyzer.assert_not_called()
        self.processor.assert_not_called()

    def testUpdate(self):
        # Update count correctly
        fileId = str(uuid.uuid1())
        resp = self.client.put(
            '/music/' + fileId + '.mp3',
            data=json.dumps({'count': 4}),
            content_type='text/json'
        )
        self.assertEqual(resp.status_code, 200)
        self.update_analyzer.assert_called_once_with('music', fileId, '.mp3',
                                                     {'count': 4})
        self.upload_analyzer.assert_not_called()
        self.processor.assert_called_once_with('data_dir', 'music', fileId,
                                               '.mp3', ['UpdateChange'])
        self.assertEqual(json.loads(six.text_type(resp.data, 'ascii')),
                         {'status': 'OK'})
        self.update_analyzer.reset_mock()
        self.processor.reset_mock()

        # Update artist and title correctly
        resp = self.client.put(
            '/music/' + fileId + '.mp3',
            data=json.dumps({'artist': 'A', 'title': 'B'}),
            content_type='text/json'
        )
        self.assertEqual(resp.status_code, 200)
        self.update_analyzer.assert_called_once_with(
            'music', fileId, '.mp3', {'artist': 'A', 'title': 'B'}
        )
        self.processor.assert_called_once_with(
            'data_dir', 'music', fileId, '.mp3',
            ['UpdateChange']
        )
        self.update_analyzer.reset_mock()
        self.processor.reset_mock()

        # Update with invalid json format
        resp = self.client.put(
            '/music/' + fileId + '.mp3',
            data='{ a: " }',
            content_type='text/json'
        )
        self.assertEqual(resp.status_code, 422)
        self.assertTrue(b'not valid JSON' in resp.data)
        self.update_analyzer.assert_not_called()

        # Update with invalid unicode format
        resp = self.client.put(
            '/music/' + fileId + '.mp3',
            data=b'\xFF',
            content_type='text/json'
        )
        self.assertEqual(resp.status_code, 422)
        self.assertTrue(b'not valid UTF-8 data' in resp.data)
        self.update_analyzer.assert_not_called()

    def testDelete(self):
        from klangbecken_api import FileDeletion
        fileId = str(uuid.uuid1())
        resp = self.client.delete('/music/' + fileId + '.mp3',)
        self.assertEqual(resp.status_code, 200)
        self.update_analyzer.assert_not_called()
        self.upload_analyzer.assert_not_called()
        self.processor.assert_called_once_with('data_dir', 'music', fileId,
                                               '.mp3', [FileDeletion()])

        self.assertEqual(json.loads(six.text_type(resp.data, 'ascii')),
                         {'status': 'OK'})
        self.upload_analyzer.reset_mock()
        self.processor.reset_mock()


class AuthTestCase(unittest.TestCase):
    def setUp(self):
        from klangbecken_api import KlangbeckenAPI

        app = KlangbeckenAPI(
            'inexistent_dir',
            'secret',
            upload_analyzers=[lambda *args: []],
            update_analyzers=[lambda *args: []],
            processors=[lambda *args: None],
        )
        self.client = Client(app, BaseResponse)

    def testFailingAuth(self):
        resp = self.client.post('/music/')
        self.assertEqual(resp.status_code, 401)
        resp = self.client.put('/jingles/' + str(uuid.uuid1()) + '.mp3')
        self.assertEqual(resp.status_code, 401)
        resp = self.client.delete('/music/' + str(uuid.uuid1()) + '.ogg')
        self.assertEqual(resp.status_code, 401)
        resp = self.client.post('/logout/')
        self.assertEqual(resp.status_code, 401)

    def testFailingLogin(self):
        resp = self.client.get('/login/')
        self.assertEqual(resp.status_code, 401)
        self.assertNotIn('Set-Cookie', resp.headers)

        resp = self.client.post('/login/')
        self.assertEqual(resp.status_code, 401)
        self.assertNotIn('Set-Cookie', resp.headers)

    def _testLogin(self, method):
        method_func = getattr(self.client, method.lower())
        resp = method_func('/login/', environ_base={'REMOTE_USER': 'xyz'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(json.loads(six.text_type(resp.data, 'ascii')),
                         {'status': 'OK', 'user': 'xyz'})
        self.assertIn('Set-Cookie', resp.headers)
        self.assertIn('session', resp.headers['Set-Cookie'])
        self.assertIn('user', resp.headers['Set-Cookie'])

        # See if we're still logged in
        resp = self.client.get('/login/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(json.loads(six.text_type(resp.data, 'ascii')),
                         {'status': 'OK', 'user': 'xyz'})

        # Funny user name
        resp = self.client.get('/login/', environ_base={'REMOTE_USER': 'äöü'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(json.loads(six.text_type(resp.data, 'ascii')),
                         {'status': 'OK', 'user': 'äöü'})

    def testLoginGet(self):
        self._testLogin('get')

    def testLoginPost(self):
        self._testLogin('post')

    def testLogout(self):
        resp = self.client.post('/login/', environ_base={'REMOTE_USER': 'abc'})
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post('/logout/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Set-Cookie', resp.headers)
        self.assertIn('session', resp.headers['Set-Cookie'])
        self.assertNotIn('user', resp.headers['Set-Cookie'])

    def testAuthorization(self):
        resp = self.client.post('/login/', environ_base={'REMOTE_USER': 'abc'})
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post('/music/',
                                data={'file': (io.BytesIO(b'xyz'),
                                               'test.mp3')})
        self.assertEqual(resp.status_code, 200)
        resp = self.client.put('/jingles/' + str(uuid.uuid1()) + '.mp3',
                               data=json.dumps({}))
        self.assertEqual(resp.status_code, 200)
        resp = self.client.delete('/music/' + str(uuid.uuid1()) + '.ogg')
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post('/logout/')
        self.assertEqual(resp.status_code, 200)


class AnalyzersTestCase(unittest.TestCase):
    def setUp(self):
        self.current_path = os.path.dirname(os.path.realpath(__file__))
        fd, name = tempfile.mkstemp()
        os.write(fd, b'\0' * 1024)
        os.close(fd)
        self.invalid_file = name

    def tearDown(self):
        os.remove(self.invalid_file)

    def testUpdateAnalyzer(self):
        from klangbecken_api import update_data_analyzer, MetadataChange

        # Correct single update
        self.assertEqual(
            update_data_analyzer('playlist', 'id', '.ext', {'artist': 'A'}),
            [MetadataChange('artist', 'A')]
        )

        # Correct multiple updates
        changes = update_data_analyzer('playlist', 'id', '.ext',
                                       {'artist': 'A', 'title': 'Ø'})
        self.assertEqual(len(changes), 2)
        self.assertTrue(MetadataChange('artist', 'A') in changes)
        self.assertTrue(MetadataChange('title', 'Ø') in changes)

        # Update count with wrong data type
        self.assertRaises(
            UnprocessableEntity,
            update_data_analyzer,
            'playlist', 'id', '.ext', {'count': '1'}
        )

        # Update artist with wrong data type
        self.assertRaises(
            UnprocessableEntity,
            update_data_analyzer,
            'playlist', 'id', '.ext', {'artist': []}
        )

        # Update not allowed property (original_filename)
        self.assertRaises(
            UnprocessableEntity,
            update_data_analyzer,
            'playlist', 'id', '.ext', {'original_filename': 'test.mp3'}
        )

        # Update with wrong data format
        self.assertRaises(
            UnprocessableEntity,
            update_data_analyzer,
            'playlist', 'id', '.ext', [['artist', 'A']]
        )

    def testRawFileAnalyzer(self):
        import time
        from klangbecken_api import (raw_file_analyzer, FileAddition,
                                     MetadataChange)

        # Missing file
        self.assertRaises(UnprocessableEntity, raw_file_analyzer, 'music',
                          'fileId', '.mp3', None)

        # Invalid file
        self.assertRaises(UnprocessableEntity, raw_file_analyzer,
                          'music', 'fileId', '.xml', 'file')

        # Correct file
        fileStorage = FileStorage(filename='filename-äöü')
        result = raw_file_analyzer('jingles', 'fileId', '.ogg', fileStorage)

        # Assure file is reset correctly
        self.assertEqual(fileStorage.tell(), 0)
        self.assertFalse(fileStorage.closed)

        self.assertEqual(result[0], FileAddition(fileStorage))
        self.assertTrue(MetadataChange('playlist', 'jingles') in result)
        self.assertTrue(MetadataChange('id', 'fileId') in result)
        self.assertTrue(MetadataChange('ext', '.ogg') in result)
        self.assertTrue(MetadataChange('original_filename', 'filename-äöü') in
                        result)
        t = [ch for ch in result if (isinstance(ch, MetadataChange) and
                                     ch.key == 'import_timestamp')][0]
        self.assertTrue(time.time() - t.value < 1)
        self.assertTrue(MetadataChange('count', 1) in result)

    def testMutagenTagAnalyzer(self):
        from klangbecken_api import mutagen_tag_analyzer
        from klangbecken_api import MetadataChange as Change

        # Test regular files
        for ext in ['.mp3', '.ogg', '.flac']:
            path = os.path.join(self.current_path, 'audio', 'silence' + ext)
            with open(path, 'rb') as f:
                fs = FileStorage(f)
                changes = mutagen_tag_analyzer('music', 'fileId', ext, fs)
                self.assertEqual(len(changes), 4)
                self.assertIn(Change('artist', 'Silence Artist'), changes)
                self.assertIn(Change('title', 'Silence Track'), changes)
                self.assertIn(Change('album', 'Silence Album'), changes)
                self.assertIn(Change('length', 1.0), changes)

                # Assure file is reset correctly
                self.assertEqual(f.tell(), 0)
                self.assertFalse(f.closed)

        # Test regular files with unicode tags
        for suffix in ['-jointstereo.mp3', '-stereo.mp3', '.ogg', '.flac']:
            extra, ext = suffix.split('.')
            ext = '.' + ext
            name = 'silence-unicode' + extra + ext
            path = os.path.join(self.current_path, 'audio', name)
            with open(path, 'rb') as f:
                fs = FileStorage(f)
                changes = mutagen_tag_analyzer('music', 'fileId', ext, fs)
                self.assertEqual(len(changes), 4)
                self.assertIn(Change('artist', 'ÀÉÈ'), changes)
                self.assertIn(Change('title', 'ÄÖÜ'), changes)
                self.assertIn(Change('album', '☀⚛♬'), changes)
                self.assertIn(Change('length', 1.0), changes)

        # Test MP3 without any tags
        path = os.path.join(self.current_path, 'audio', 'silence-stripped.mp3')
        with open(path, 'rb') as f:
            fs = FileStorage(f)
            changes = mutagen_tag_analyzer('music', 'fileId', '.mp3', fs)
            self.assertEqual(len(changes), 4)
            self.assertIn(Change('artist', ''), changes)
            self.assertIn(Change('title', ''), changes)
            self.assertIn(Change('album', ''), changes)
            self.assertIn(Change('length', 1.0), changes)

        # Test invalid files
        for ext in ['.mp3', '.ogg', '.flac']:
            path = os.path.join(self.current_path, 'audio', 'silence' + ext)
            fs = FileStorage(io.BytesIO(b'\0' * 1024))
            with self.assertRaises(UnprocessableEntity):
                mutagen_tag_analyzer('music', 'fileId', ext, fs)

    def _analyzeOneFile(self, prefix, postfix, gain, cue_in, cue_out):
        from klangbecken_api import ffmpeg_audio_analyzer
        from klangbecken_api import MetadataChange

        name = prefix + postfix.split('.')[0]
        ext = '.' + postfix.split('.')[1]

        current_path = os.path.dirname(os.path.realpath(__file__))
        path = os.path.join(current_path, 'audio', name + ext)
        with open(path, 'rb') as f:
            fs = FileStorage(f)

            changes = ffmpeg_audio_analyzer('music', name, ext, fs)
            self.assertEqual(len(changes), 3)
            for change in changes:
                self.assertIsInstance(change, MetadataChange)
            changes = {key: val for key, val in changes}
            self.assertEqual(set(changes.keys()),
                             set('track_gain cue_in cue_out'.split()))

            # Track gain negativ and with units
            measured_gain = changes['track_gain']
            self.assertTrue(measured_gain.endswith(' dB'))

            # Be within ±0.5 dB of expected gain value
            self.assertLess(abs(float(measured_gain[:-3]) - gain), 0.5)

            # Be within the expected values for cue points
            # Dont fade in late, or fade out early!
            self.assertGreater(float(changes['cue_in']), cue_in - 0.1)
            self.assertLess(float(changes['cue_in']), cue_in + 0.01)
            self.assertGreater(float(changes['cue_out']), cue_out - 0.01)
            self.assertLess(float(changes['cue_out']), cue_out + 0.1)

            # Assure file is reset correctly
            self.assertEqual(f.tell(), 0)
            self.assertFalse(f.closed)

    def testFFmpegAudioAnalyzer(self):
        from klangbecken_api import ffmpeg_audio_analyzer

        test_data = [
            {
                'prefix': 'padded',
                'gain': -17,
                'cue_in': 0.2,
                'cue_out': 0.8,
            },
            {
                'prefix': 'padded-start',
                'gain': -3.33,
                'cue_in': 1,
                'cue_out': 2,
            },
            {
                'prefix': 'padded-end',
                'gain': -3.55,
                'cue_in': 0,
                'cue_out': 1,
            },
            {
                'prefix': 'silence-unicode',
                'gain': +64,
                'cue_in': 0,
                'cue_out': 0,
            },
            {
                'prefix': 'interleaved',
                'gain': -14.16,
                'cue_in': 0.2,
                'cue_out': 0.8,
            },
        ]

        for data in test_data:
            for ext in '-jointstereo.mp3 -stereo.mp3 .ogg .flac'.split():
                self._analyzeOneFile(postfix=ext, **data)

        # invalid file
        with self.assertRaises(UnprocessableEntity):
            with open(self.invalid_file, 'rb') as f:
                fs = FileStorage(f)
                ffmpeg_audio_analyzer('music', 'id1', '.mp3', fs)


class ProcessorsTestCase(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        os.mkdir(os.path.join(self.tempdir, 'music'))

        current_path = os.path.dirname(os.path.realpath(__file__))
        for ext in '.mp3 -stripped.mp3 .ogg .flac'.split():
            shutil.copyfile(
                os.path.join(current_path, 'audio', 'silence' + ext),
                os.path.join(self.tempdir, 'music', 'silence' + ext)
            )

        with open(os.path.join(self.tempdir, 'index.json'), 'w') as f:
            print('{}', file=f)
        open(os.path.join(self.tempdir, 'music.m3u'), 'w').close()
        open(os.path.join(self.tempdir, 'jingles.m3u'), 'w').close()

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def testRawFileProcessor(self):
        from klangbecken_api import raw_file_processor
        from klangbecken_api import FileAddition, FileDeletion, MetadataChange

        file_ = FileStorage(io.BytesIO(b'abc'), 'filename-éàè.txt')
        addition = FileAddition(file_)
        change = MetadataChange('key', 'value')
        delete = FileDeletion()

        # File addition
        raw_file_processor(self.tempdir, 'music', 'id1', '.mp3', [addition])
        path = os.path.join(self.tempdir, 'music', 'id1.mp3')
        self.assertTrue(os.path.isfile(path))
        with open(path) as f:
            self.assertEqual(f.read(), 'abc')

        # File change (nothing happens) and deletion
        raw_file_processor(self.tempdir, 'music', 'id1', '.mp3', [change])
        raw_file_processor(self.tempdir, 'music', 'id1', '.mp3', [delete])
        self.assertTrue(not os.path.isfile(path))

        # Invalid change (not found)
        self.assertRaises(NotFound, raw_file_processor,
                          self.tempdir, 'music', 'id1', '.mp3', [change])

        # Invalid deletion (not found)
        self.assertRaises(NotFound, raw_file_processor,
                          self.tempdir, 'music', 'id1', '.mp3', [delete])

        # Completely invalid change
        self.assertRaises(ValueError, raw_file_processor,
                          self.tempdir, 'music', 'id1', '.mp3', ['invalid'])

    def testIndexProcessor(self):
        from klangbecken_api import index_processor
        from klangbecken_api import FileAddition, FileDeletion, MetadataChange

        index_path = os.path.join(self.tempdir, 'index.json')

        # Add two new files
        file_ = FileStorage(io.BytesIO(b'abc'), 'filename.txt')
        index_processor(self.tempdir, 'music', 'fileId1', '.mp3',
                        [FileAddition(file_)])
        index_processor(self.tempdir, 'music', 'fileId2', '.ogg',
                        [FileAddition(file_)])

        with open(index_path) as f:
            data = json.load(f)

        self.assertTrue('fileId1' in data)
        self.assertTrue('fileId2' in data)

        # Set some initial metadata
        index_processor(self.tempdir, 'music', 'fileId1', '.mp3',
                        [MetadataChange('key1', 'value1')])
        index_processor(self.tempdir, 'music', 'fileId2', '.ogg',
                        [MetadataChange('key1', 'value1'),
                         MetadataChange('key2', 'value2')])

        with open(index_path) as f:
            data = json.load(f)

        self.assertTrue('key1' in data['fileId1'])
        self.assertEqual(data['fileId1']['key1'], 'value1')
        self.assertTrue('key1' in data['fileId2'])
        self.assertEqual(data['fileId2']['key1'], 'value1')
        self.assertTrue('key2' in data['fileId2'])
        self.assertEqual(data['fileId2']['key2'], 'value2')

        # Modify metadata
        index_processor(self.tempdir, 'music', 'fileId1', '.mp3',
                        [MetadataChange('key1', 'value1-1'),
                         MetadataChange('key2', 'value2-1')])
        index_processor(self.tempdir, 'music', 'fileId2', '.ogg',
                        [MetadataChange('key2', 'value2-1-œ')])

        with open(index_path) as f:
            data = json.load(f)

        self.assertTrue('key1' in data['fileId1'])
        self.assertEqual(data['fileId1']['key1'], 'value1-1')
        self.assertTrue('key2' in data['fileId1'])
        self.assertEqual(data['fileId1']['key2'], 'value2-1')
        self.assertTrue('key1' in data['fileId2'])
        self.assertEqual(data['fileId2']['key1'], 'value1')
        self.assertTrue('key2' in data['fileId2'])
        self.assertEqual(data['fileId2']['key2'], 'value2-1-œ')

        # Delete one file
        index_processor(self.tempdir, 'music', 'fileId1', '.mp3',
                        [FileDeletion()])

        with open(index_path) as f:
            data = json.load(f)

        self.assertTrue('fileId1' not in data)
        self.assertTrue('fileId2' in data)

        # Try duplicating file ids
        with self.assertRaisesRegexp(UnprocessableEntity, 'Duplicate'):
            index_processor(self.tempdir, 'music', 'fileId2', '.ogg',
                            [FileAddition(file_)])
        with self.assertRaisesRegexp(UnprocessableEntity, 'Duplicate'):
            index_processor(self.tempdir, 'jingles', 'fileId2', '.mp3',
                            [FileAddition(file_)])
        with self.assertRaisesRegexp(UnprocessableEntity, 'Duplicate'):
            index_processor(self.tempdir, 'music', 'fileId2', '.mp3',
                            [FileAddition(file_)])

        # Try modifying non existent files
        with self.assertRaises(NotFound):
            index_processor(self.tempdir, 'music', 'fileIdXY', '.ogg',
                            [MetadataChange('key', 'val')])

        # Try deleting non existent file ids
        with self.assertRaises(NotFound):
            index_processor(self.tempdir, 'music', 'fileIdXY', '.ogg',
                            [FileDeletion()])

        with open(index_path) as f:
            data = json.load(f)
        self.assertTrue('fileId2' in data)
        self.assertTrue('fileXY' not in data)

        # Completely invalid change
        self.assertRaises(ValueError, index_processor,
                          self.tempdir, 'music', 'id1', '.mp3', ['invalid'])

    def testFileTagProcessor(self):
        from klangbecken_api import file_tag_processor
        from klangbecken_api import MetadataChange
        from klangbecken_api import FileAddition
        from klangbecken_api import FileDeletion
        from mutagen import File

        # No-ops
        file_tag_processor(self.tempdir, 'nonexistant', 'fileIdZZ', '.mp3', [
            FileAddition(''),
            MetadataChange('id', 'abc'),
            MetadataChange('playlist', 'abc'),
            MetadataChange('ext', 'abc'),
            MetadataChange('original_filename', 'abc'),
            MetadataChange('import_timestamp', 'abc'),
            MetadataChange('count', 'abc'),
            MetadataChange('length', 'abc'),
            MetadataChange('nonexistant', 'abc'),
            FileDeletion(),
        ])

        changes = {
            'artist': 'New Artist (๛)',
            'title': 'New Title (᛭)',
            'album': 'New Album (٭)',
            'cue_in': '0.123',
            'cue_out': '123',
            'track_gain': '-12 dB',
        }
        metadata_changes = [MetadataChange(key, val) for key, val
                            in changes.items()]

        # Valid files
        for ext in '.mp3 -stripped.mp3 .ogg .flac'.split():
            path = os.path.join(self.tempdir, 'music', 'silence' + ext)
            mutagenfile = File(path, easy=True)

            # Make sure tags are not already the same before updating
            for key, val in changes.items():
                self.assertNotEqual(val, mutagenfile.get(key, [''])[0])

            # Update and verify tags
            file_tag_processor(self.tempdir, 'music', 'silence', ext,
                               metadata_changes)
            mutagenfile = File(path, easy=True)
            for key, val in changes.items():
                self.assertEqual(len(mutagenfile.get(key, [''])), 1)
                self.assertEqual(val, mutagenfile.get(key, [''])[0])

    def testPlaylistProcessor(self):
        from klangbecken_api import playlist_processor
        from klangbecken_api import FileDeletion, MetadataChange

        music_path = os.path.join(self.tempdir, 'music.m3u')
        jingles_path = os.path.join(self.tempdir, 'jingles.m3u')

        # Update playlist count (initial)
        playlist_processor(self.tempdir, 'music', 'fileId1', '.mp3',
                           [MetadataChange('count', 2)])

        with open(music_path) as f:
            lines = f.read().split('\n')
        entries = [l for l in lines if l.endswith('music/fileId1.mp3')]
        self.assertEqual(len(entries), 2)

        with open(jingles_path) as f:
            data = f.read()
        self.assertEqual(data, '')

        # Update playlist count
        playlist_processor(self.tempdir, 'music', 'fileId1', '.mp3',
                           [MetadataChange('count', 4)])

        with open(music_path) as f:
            lines = f.read().split('\n')
        entries = [l for l in lines if l.endswith('music/fileId1.mp3')]
        self.assertEqual(len(entries), 4)

        with open(jingles_path) as f:
            data = f.read()
        self.assertEqual(data, '')

        # Set playlist count to zero (same as delete)
        playlist_processor(self.tempdir, 'music', 'fileId1', '.mp3',
                           [MetadataChange('count', 0)])

        with open(music_path) as f:
            data = f.read()
        self.assertEqual(data, '')

        with open(jingles_path) as f:
            data = f.read()
        self.assertEqual(data, '')

        # Add more files to playlist
        playlist_processor(self.tempdir, 'music', 'fileId1', '.mp3',
                           [MetadataChange('count', 2)])
        playlist_processor(self.tempdir, 'music', 'fileId2', '.ogg',
                           [MetadataChange('count', 1)])
        playlist_processor(self.tempdir, 'music', 'fileId3', '.flac',
                           [MetadataChange('count', 3)])
        playlist_processor(self.tempdir, 'jingles', 'fileId4', '.mp3',
                           [MetadataChange('count', 2)])
        playlist_processor(self.tempdir, 'jingles', 'fileId5', '.mp3',
                           [MetadataChange('count', 3)])

        with open(music_path) as f:
            lines = [l.strip() for l in f.readlines()]
        entries = [l for l in lines if l.endswith('music/fileId1.mp3')]
        self.assertEqual(len(entries), 2)
        entries = [l for l in lines if l.endswith('music/fileId2.ogg')]
        self.assertEqual(len(entries), 1)
        entries = [l for l in lines if l.endswith('music/fileId3.flac')]
        self.assertEqual(len(entries), 3)

        with open(jingles_path) as f:
            lines = [l.strip() for l in f.readlines()]
        entries = [l for l in lines if l.endswith('jingles/fileId4.mp3')]
        self.assertEqual(len(entries), 2)
        entries = [l for l in lines if l.endswith('jingles/fileId5.mp3')]
        self.assertEqual(len(entries), 3)

        # Delete non existing file (must be possible)
        playlist_processor(self.tempdir, 'music', 'fileIdXY', '.ogg',
                           [FileDeletion()])
        with open(music_path) as f:
            lines = [l.strip() for l in f.readlines()]
        self.assertEqual(len(lines), 6)
        self.assertTrue(all(lines))

        with open(jingles_path) as f:
            lines = [l.strip() for l in f.readlines()]
        self.assertEqual(len(lines), 5)
        self.assertTrue(all(lines))

        # Delete existing file
        playlist_processor(self.tempdir, 'music', 'fileId1', '.mp3',
                           [FileDeletion()])
        with open(music_path) as f:
            lines = [l.strip() for l in f.readlines()]
        self.assertEqual(len(lines), 4)
        self.assertTrue(all(lines))
        entries = [l for l in lines if l.endswith('music/fileId1.mp3')]
        self.assertListEqual(entries, [])

        with open(jingles_path) as f:
            lines = [l.strip() for l in f.readlines()]
        self.assertEqual(len(lines), 5)
        self.assertTrue(all(lines))

        # Multiple deletes
        playlist_processor(self.tempdir, 'music', 'fileId3', '.flac',
                           [FileDeletion()])
        playlist_processor(self.tempdir, 'jingles', 'fileId4', '.mp3',
                           [FileDeletion()])
        playlist_processor(self.tempdir, 'jingles', 'fileId5', '.mp3',
                           [FileDeletion()])

        with open(music_path) as f:
            lines = [l.strip() for l in f.readlines()]
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].endswith('music/fileId2.ogg'))

        with open(jingles_path) as f:
            data = f.read()
        self.assertEqual(data, '')


class StandaloneWebApplicationStartupTestCase(unittest.TestCase):
    def setUp(self):
        self.current_path = os.path.dirname(os.path.realpath(__file__))
        self.tempdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def testNoFFmpegWarning(self):
        from klangbecken_api import StandaloneWebApplication

        with capture(StandaloneWebApplication, self.tempdir) as output:
            self.assertNotIn("WARNING", output)

    def testDirStructure(self):
        from klangbecken_api import StandaloneWebApplication
        self.assertFalse(os.path.isdir(os.path.join(self.tempdir, 'music')))

        StandaloneWebApplication(self.tempdir)
        self.assertTrue(os.path.isdir(os.path.join(self.tempdir, 'music')))

        with open(os.path.join(self.tempdir, 'music', 'abc.txt'), 'w'):
            pass

        StandaloneWebApplication(self.tempdir)
        self.assertTrue(os.path.isdir(os.path.join(self.tempdir, 'music')))
        self.assertTrue(os.path.isfile(os.path.join(self.tempdir, 'music',
                                                    'abc.txt')))


class StandaloneWebApplicationTestCase(unittest.TestCase):
    def setUp(self):
        from klangbecken_api import StandaloneWebApplication

        self.current_path = os.path.dirname(os.path.realpath(__file__))
        self.tempdir = tempfile.mkdtemp()

        app = StandaloneWebApplication(self.tempdir)
        self.client = Client(app, BaseResponse)

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def testIndexHtml(self):
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data.startswith(b'<!DOCTYPE html>'))
        self.assertIn(b'RaBe Klangbecken', resp.data)
        resp.close()

    def testApi(self):
        # Login
        resp = self.client.get('/api/login/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(json.loads(six.text_type(resp.data, 'ascii')),
                         {'status': 'OK', 'user': 'dummyuser'})
        resp.close()

        # Upload
        path = os.path.join(self.current_path, 'audio',
                            'silence-unicode-jointstereo.mp3')
        with open(path, 'rb') as f:
            resp = self.client.post(
                '/api/music/',
                data={'file': (f, 'silence-unicode-jointstereo.mp3')},
            )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(six.text_type(resp.data, 'ascii'))
        fileId = list(data.keys())[0]
        self.assertEqual(fileId, six.text_type(uuid.UUID(fileId)))
        expected = {
            'original_filename': 'silence-unicode-jointstereo.mp3',
            'length': 1.0,
            'album': '☀⚛♬',
            'title': 'ÄÖÜ',
            'artist': 'ÀÉÈ',
            'ext': '.mp3',
            'count': 1,
            'playlist': 'music',
            'id': fileId
        }
        self.assertTrue(set(expected.items()) <= set(data[fileId].items()))
        resp.close()

        # Update
        resp = self.client.put(
            '/api/music/' + fileId + '.mp3',
            data=json.dumps({'count': 4}),
            content_type='text/json'
        )
        self.assertEqual(resp.status_code, 200)
        resp.close()

        # Get file
        resp = self.client.get('/data/music/' + fileId + '.mp3')
        self.assertEqual(resp.status_code, 200)
        resp.close()

        # Get index.json
        resp = self.client.get('/data/index.json')
        self.assertEqual(resp.status_code, 200)
        resp.close()

        # Delete file
        resp = self.client.delete('/api/music/' + fileId + '.mp3',)
        self.assertEqual(resp.status_code, 200)
        resp.close()

        # Logout
        resp = self.client.post('/api/logout/')
        self.assertEqual(resp.status_code, 200)
        resp.close()

        # Verify that we are logged out
        resp = self.client.post('/api/music/')
        self.assertEqual(resp.status_code, 401)
        resp.close()


class DataDirCreatorTestCase(unittest.TestCase):
    def setUp(self):
        self.current_path = os.path.dirname(os.path.realpath(__file__))
        self.tempdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def testDataDirCheckOnly(self):
        from klangbecken_api import check_and_crate_data_dir, PLAYLISTS

        for playlist in PLAYLISTS:
            path = os.path.join(self.tempdir, playlist)
            with self.assertRaises(Exception):
                check_and_crate_data_dir(self.tempdir, False)
            os.mkdir(path)

        for playlist in PLAYLISTS:
            path = os.path.join(self.tempdir, playlist + '.m3u')
            with self.assertRaises(Exception):
                check_and_crate_data_dir(self.tempdir, False)
            with open(path, 'a'):
                pass
        with self.assertRaises(Exception):
                check_and_crate_data_dir(self.tempdir, False)

        with open(os.path.join(self.tempdir, 'index.json'), 'w'):
                pass

        check_and_crate_data_dir(self.tempdir, False)

    def testDataDirCreation(self):
        from klangbecken_api import check_and_crate_data_dir, PLAYLISTS
        check_and_crate_data_dir(self.tempdir)
        for playlist in PLAYLISTS:
            path = os.path.join(self.tempdir, playlist)
            self.assertTrue(os.path.isdir(path))
            path += '.m3u'
            self.assertTrue(os.path.isfile(path))

        path = os.path.join(self.tempdir, 'index.json')
        self.assertTrue(os.path.isfile(path))
        with open(path) as f:
            self.assertEqual(json.load(f), {})


class ImporterTestCase(unittest.TestCase):
    pass
