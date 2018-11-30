import json
import mock
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


class APITest(unittest.TestCase):
    def setUp(self):
        from klangbecken_api import KlangbeckenAPI
        from werkzeug.test import Client
        from werkzeug.wrappers import BaseResponse

        self.analyzer = mock.Mock(return_value=['Change'])
        self.processor = mock.MagicMock()

        app = KlangbeckenAPI(
            analyzers=[self.analyzer],
            processors=[self.processor],
            disable_auth=True,
        )
        self.client = Client(app, BaseResponse)

    def tearDown(self):
        pass

    def test_urls(self):
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 404)

        resp = self.client.get('/music/')
        self.assertEqual(resp.status_code, 405)

        resp = self.client.get('/jingles/')
        self.assertEqual(resp.status_code, 405)

        resp = self.client.post('/jingles')
        self.assertEqual(resp.status_code, 301)

        resp = self.client.get('/nonexistant/')
        self.assertEqual(resp.status_code, 404)

    def test_update(self):
        from klangbecken_api import MetadataChange

        # Update count correctly
        fileId = str(uuid.uuid1())
        resp = self.client.put(
            '/music/' + fileId + '.mp3',
            data=json.dumps({'count': 4}),
            content_type='text/json'
        )
        self.assertEqual(resp.status_code, 200)
        self.analyzer.assert_not_called()
        self.processor.assert_called_once_with('music', fileId, '.mp3',
                                               [MetadataChange('count', 4)])

        self.analyzer.reset_mock()
        self.processor.reset_mock()

        # Update artist correctly
        resp = self.client.put(
            '/music/' + fileId + '.mp3',
            data=json.dumps({'artist': 'A'}),
            content_type='text/json'
        )
        self.assertEqual(resp.status_code, 200)
        self.analyzer.assert_not_called()
        self.processor.assert_called_once_with('music', fileId, '.mp3',
                                               [MetadataChange('artist', 'A')])

        self.analyzer.reset_mock()
        self.processor.reset_mock()

        # Update count with wrong data type
        resp = self.client.put(
            '/music/' + fileId + '.mp3',
            data=json.dumps({'count': '1'}),
            content_type='text/json'
        )
        self.assertEqual(resp.status_code, 422)
        self.analyzer.assert_not_called()
        self.processor.assert_not_called()

        self.analyzer.reset_mock()
        self.processor.reset_mock()

        self.analyzer.reset_mock()
        self.processor.reset_mock()

        # Update artist with wrong data type
        resp = self.client.put(
            '/music/' + fileId + '.mp3',
            data=json.dumps({'artist': []}),
            content_type='text/json'
        )
        self.assertEqual(resp.status_code, 422)
        self.analyzer.assert_not_called()
        self.processor.assert_not_called()

        self.analyzer.reset_mock()
        self.processor.reset_mock()

        # Update not allowed property (original_filename)
        resp = self.client.put(
            '/music/' + fileId + '.mp3',
            data=json.dumps({'original_filename': 'test.mp3'}),
            content_type='text/json'
        )
        self.assertEqual(resp.status_code, 422)
        self.analyzer.assert_not_called()
        self.processor.assert_not_called()

        self.analyzer.reset_mock()
        self.processor.reset_mock()

        # Update with wrong data format
        resp = self.client.put(
            '/music/' + fileId + '.mp3',
            data=json.dumps([['artist', 'A']]),
            content_type='text/json'
        )
        self.assertEqual(resp.status_code, 422)
        self.analyzer.assert_not_called()
        self.processor.assert_not_called()

        self.analyzer.reset_mock()
        self.processor.reset_mock()

        # Update with invalid json format
        resp = self.client.put(
            '/music/' + fileId + '.mp3',
            data='{ a: " }',
            content_type='text/json'
        )
        self.assertEqual(resp.status_code, 422)
        self.analyzer.assert_not_called()
        self.processor.assert_not_called()

        self.analyzer.reset_mock()
        self.processor.reset_mock()
