from __future__ import unicode_literals, print_function

import json
import mock
import os
import six
import unittest
import uuid


class BackendTest(unittest.TestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_application(self):
        from klangbecken_api import application, KlangbeckenAPI

        self.assertTrue(isinstance(application, KlangbeckenAPI))
        self.assertTrue(callable(application))


class APITestCase(unittest.TestCase):
    def setUp(self):
        from klangbecken_api import (KlangbeckenAPI, FileAddition,
                                     MetadataChange)
        from werkzeug.test import Client
        from werkzeug.wrappers import BaseResponse

        self.upload_analyzer = mock.Mock(return_value=[
            FileAddition('testfile'),
            MetadataChange('testkey', 'testvalue')
        ])
        self.update_analyzer = mock.Mock(return_value=['UpdateChange'])
        self.processor = mock.MagicMock()

        app = KlangbeckenAPI(
            upload_analyzers=[self.upload_analyzer],
            update_analyzers=[self.update_analyzer],
            processors=[self.processor],
            disable_auth=True,
        )
        self.client = Client(app, BaseResponse)

    def tearDown(self):
        pass

    def testUrls(self):
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 404)

        resp = self.client.get('/music/')
        self.assertEqual(resp.status_code, 405)

        resp = self.client.get('/jingles/')
        self.assertEqual(resp.status_code, 405)

        resp = self.client.get('/nonexistant/')
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
        from werkzeug.datastructures import FileStorage
        from io import BytesIO

        resp = self.client.post(
            '/music/',
            data={'file': (BytesIO(b'testcontent'), 'test.mp3')},
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
        self.assertEqual(args[3].read(), b'testcontent')

        self.processor.assert_called_once_with('music', fileId, '.mp3', [
            FileAddition('testfile'), MetadataChange('testkey', 'testvalue')
        ])

        self.upload_analyzer.reset_mock()
        self.processor.reset_mock()

        # wrong attribute name
        resp = self.client.post(
            '/music/',
            data={'not-file': (BytesIO(b'testcontent'), 'test.mp3')},
        )
        self.assertEqual(resp.status_code, 422)
        self.assertTrue(b'No attribute named \'file\' found' in resp.data)
        self.update_analyzer.assert_not_called()
        self.upload_analyzer.assert_not_called()
        self.processor.assert_not_called()

        # file as normal text attribute
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
        self.processor.assert_called_once_with('music', fileId, '.mp3',
                                               ['UpdateChange'])
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
            'music', fileId, '.mp3',
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
        self.processor.assert_called_once_with('music', fileId, '.mp3',
                                               [FileDeletion()])

        self.assertEqual(json.loads(six.text_type(resp.data, 'ascii')),
                         {'status': 'OK'})
        self.upload_analyzer.reset_mock()
        self.processor.reset_mock()


class UpdateAnalyzerTestCase(unittest.TestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def testUpdateAnalyzer(self):
        from klangbecken_api import update_analyzer, MetadataChange
        from werkzeug.exceptions import UnprocessableEntity

        # Correct single update
        self.assertEqual(
            update_analyzer('playlist', 'id', '.ext', {'artist': 'A'}),
            [MetadataChange('artist', 'A')]
        )

        # Correct multiple updates
        changes = update_analyzer('playlist', 'id', '.ext',
                                  {'artist': 'A', 'title': 'T'})
        self.assertEqual(len(changes), 2)
        self.assertTrue(MetadataChange('artist', 'A') in changes)
        self.assertTrue(MetadataChange('title', 'T') in changes)

        # Update count with wrong data type
        self.assertRaises(
            UnprocessableEntity,
            update_analyzer,
            'playlist', 'id', '.ext', {'count': '1'}
        )

        # Update artist with wrong data type
        self.assertRaises(
            UnprocessableEntity,
            update_analyzer,
            'playlist', 'id', '.ext', {'artist': []}
        )

        # Update not allowed property (original_filename)
        self.assertRaises(
            UnprocessableEntity,
            update_analyzer,
            'playlist', 'id', '.ext', {'original_filename': 'test.mp3'}
        )

        # Update with wrong data format
        self.assertRaises(
            UnprocessableEntity,
            update_analyzer,
            'playlist', 'id', '.ext', [['artist', 'A']]
        )

    def testRawFileAnalyzer(self):
        import time
        from klangbecken_api import (raw_file_analyzer, FileAddition,
                                     MetadataChange)
        from werkzeug.datastructures import FileStorage
        from werkzeug.exceptions import UnprocessableEntity

        self.assertRaises(UnprocessableEntity, raw_file_analyzer, 'music',
                          'fileId', '.mp3', None)

        self.assertRaises(UnprocessableEntity, raw_file_analyzer,
                          'music', 'fileId', '.xml', 'file')

        fileStorage = FileStorage(filename='filename')
        result = raw_file_analyzer('jingles', 'fileId', '.ogg', fileStorage)

        self.assertEqual(result[0], FileAddition(fileStorage))
        self.assertTrue(MetadataChange('playlist', 'jingles') in result)
        self.assertTrue(MetadataChange('id', 'fileId') in result)
        self.assertTrue(MetadataChange('ext', '.ogg') in result)
        self.assertTrue(MetadataChange('original_filename', 'filename') in
                        result)
        t = [ch for ch in result if (isinstance(ch, MetadataChange) and
                                     ch.key == 'import_timestamp')][0]
        self.assertTrue(time.time() - t.value < 1)
        self.assertTrue(MetadataChange('count', 1) in result)


class ProcessorsTestCase(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tempdir = tempfile.mkdtemp()
        os.mkdir(os.path.join(self.tempdir, 'music'))
        with open(os.path.join(self.tempdir, 'index.json'), 'w') as f:
            print('{}', file=f)
        os.environ['KLANGBECKEN_DATA'] = self.tempdir

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tempdir)
        del os.environ['KLANGBECKEN_DATA']
        self.tempdir = None

    def testRawFileProcessor(self):
        from klangbecken_api import raw_file_processor
        from klangbecken_api import FileAddition, FileDeletion, MetadataChange
        from io import BytesIO
        from werkzeug.exceptions import NotFound
        from werkzeug.datastructures import FileStorage

        file_ = FileStorage(BytesIO(b'abc'), 'filename.txt')
        addition = FileAddition(file_)
        change = MetadataChange('key', 'value')
        delete = FileDeletion()
        raw_file_processor('music', 'id1', '.mp3', [addition])
        path = os.path.join(self.tempdir, 'music', 'id1.mp3')

        self.assertTrue(os.path.isfile(path))
        with open(path) as f:
            self.assertEqual(f.read(), 'abc')

        raw_file_processor('music', 'id1', '.mp3', [change])
        raw_file_processor('music', 'id1', '.mp3', [delete])
        self.assertTrue(not os.path.isfile(path))

        self.assertRaises(NotFound, raw_file_processor,
                          'music', 'id1', '.mp3', [delete])

    def testIndexProcessor(self):
        from klangbecken_api import index_processor
        from klangbecken_api import FileAddition, FileDeletion, MetadataChange
        from werkzeug.datastructures import FileStorage
        from io import BytesIO

        index_path = os.path.join(self.tempdir, 'index.json')

        file_ = FileStorage(BytesIO(b'abc'), 'filename.txt')
        index_processor('music', 'fileId1', '.mp3', [FileAddition(file_)])
        index_processor('music', 'fileId2', '.ogg', [FileAddition(file_)])

        with open(index_path) as f:
            data = json.load(f)

        self.assertTrue('fileId1' in data)
        self.assertTrue('fileId2' in data)

        index_processor('music', 'fileId1', '.mp3',
                        [MetadataChange('key1', 'value1')])
        index_processor('music', 'fileId2', '.ogg',
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

        index_processor('music', 'fileId1', '.mp3',
                        [MetadataChange('key1', 'value1-1'),
                         MetadataChange('key2', 'value2-1')])
        index_processor('music', 'fileId2', '.ogg',
                        [MetadataChange('key2', 'value2-1')])

        with open(index_path) as f:
            data = json.load(f)

        self.assertTrue('key1' in data['fileId1'])
        self.assertEqual(data['fileId1']['key1'], 'value1-1')
        self.assertTrue('key2' in data['fileId1'])
        self.assertEqual(data['fileId1']['key2'], 'value2-1')
        self.assertTrue('key1' in data['fileId2'])
        self.assertEqual(data['fileId2']['key1'], 'value1')
        self.assertTrue('key2' in data['fileId2'])
        self.assertEqual(data['fileId2']['key2'], 'value2-1')

        index_processor('music', 'fileId1', '.mp3', [FileDeletion()])

        with open(index_path) as f:
            data = json.load(f)

        self.assertTrue('fileId1' not in data)
        self.assertTrue('fileId2' in data)
