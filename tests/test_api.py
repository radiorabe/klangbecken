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

        self.upload_analyzer = mock.Mock(return_value=['UploadChange'])
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





