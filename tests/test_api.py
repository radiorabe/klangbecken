from __future__ import unicode_literals

import json
import mock
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
        self.update_analyzer.assert_not_called()
        self.upload_analyzer.assert_not_called()
        self.processor.assert_not_called()

        # file as normal text attribute
        resp = self.client.post(
            '/music/',
            data={'file': 'testcontent', 'filename': 'test.mp3'},
        )
        self.assertEqual(resp.status_code, 422)
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
        self.update_analyzer.assert_not_called()

        # Update with invalid unicode format
        resp = self.client.put(
            '/music/' + fileId + '.mp3',
            data=b'\xFF',
            content_type='text/json'
        )
        self.assertEqual(resp.status_code, 422)
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

    def test_update_analyzer(self):
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
