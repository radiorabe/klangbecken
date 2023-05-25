import io
import json
import os
import shutil
import tempfile
import unittest
import uuid
from unittest import mock

from werkzeug.test import Client


class GenericAPITestCase(unittest.TestCase):
    @mock.patch(
        "klangbecken.api.JWTAuthorizationMiddleware", lambda app, *args, **kwargs: app
    )
    def setUp(self):
        from klangbecken.api import klangbecken_api

        self.app = klangbecken_api(
            "very secret",
            "data_dir",
            "player.sock",
            upload_analyzers=[],
            update_analyzers=[],
            processors=[],
        )
        self.client = Client(self.app)

    def test_application(self):
        self.assertTrue(callable(self.app))

    def testUrls(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        resp = self.client.get("/playlist/music/")
        self.assertEqual(resp.status_code, 405)
        resp = self.client.get("/playlist/jingles/")
        self.assertEqual(resp.status_code, 405)
        resp = self.client.get("/playlist/nonexistant/")
        self.assertEqual(resp.status_code, 404)
        resp = self.client.get("/öäü/")
        self.assertEqual(resp.status_code, 404)
        resp = self.client.post("/playlist/jingles")
        self.assertIn(resp.status_code, (301, 308))
        resp = self.client.post("/playlist/music/")
        self.assertEqual(resp.status_code, 422)
        resp = self.client.post("/playlist/jingles/something")
        self.assertEqual(resp.status_code, 404)
        resp = self.client.put("/playlist/music/")
        self.assertEqual(resp.status_code, 405)
        resp = self.client.put("/playlist/jingles/something")
        self.assertEqual(resp.status_code, 404)
        resp = self.client.put("/playlist/jingles/something.mp3")
        self.assertEqual(resp.status_code, 404)
        resp = self.client.put("/playlist/music/" + str(uuid.uuid4()))
        self.assertEqual(resp.status_code, 404)
        resp = self.client.put("/playlist/music/" + str(uuid.uuid4()) + ".mp3")
        self.assertEqual(resp.status_code, 415)
        resp = self.client.put("/playlist/classics/" + str(uuid.uuid4()) + ".mp3")
        self.assertEqual(resp.status_code, 415)
        resp = self.client.put("/playlist/jingles/" + str(uuid.uuid4()) + ".mp3")
        self.assertEqual(resp.status_code, 415)
        resp = self.client.put("/playlist/jingles/" + str(uuid.uuid4()) + ".ttt")
        self.assertEqual(resp.status_code, 404)
        resp = self.client.delete("/playlist/music/")
        self.assertEqual(resp.status_code, 405)
        resp = self.client.delete("/playlist/jingles/something")
        self.assertEqual(resp.status_code, 404)
        resp = self.client.delete("/playlist/jingles/something.mp3")
        self.assertEqual(resp.status_code, 404)
        resp = self.client.delete("/playlist/music/" + str(uuid.uuid4()))
        self.assertEqual(resp.status_code, 404)
        resp = self.client.delete("/playlist/music/" + str(uuid.uuid4()) + ".mp3")
        self.assertEqual(resp.status_code, 200)
        resp = self.client.delete("/playlist/classics/" + str(uuid.uuid4()) + ".mp3")
        self.assertEqual(resp.status_code, 200)
        resp = self.client.delete("/playlist/jingles/" + str(uuid.uuid4()) + ".mp3")
        self.assertEqual(resp.status_code, 200)
        resp = self.client.delete("/playlist/music/" + str(uuid.uuid4()) + ".ttt")
        self.assertEqual(resp.status_code, 404)
        resp = self.client.get("/player/")
        self.assertEqual(resp.status_code, 404)
        self.assertIn(b"Player not running", resp.data)


class AuthTestCase(unittest.TestCase):
    def setUp(self):
        from klangbecken.api import klangbecken_api

        with mock.patch(
            "klangbecken.api.DEFAULT_UPLOAD_ANALYZERS", [lambda *args: []]
        ), mock.patch(
            "klangbecken.api.DEFAULT_UPDATE_ANALYZERS", [lambda *args: []]
        ), mock.patch(
            "klangbecken.api.DEFAULT_PROCESSORS", [lambda *args: None]
        ):
            app = klangbecken_api(
                "very secret",
                "inexistent_dir",
                "nix.sock",
            )
        self.client = Client(app)

    def testFailingAuth(self):
        resp = self.client.post("/playlist/music/")
        self.assertEqual(resp.status_code, 401)
        resp = self.client.put("/playlist/jingles/" + str(uuid.uuid4()) + ".mp3")
        self.assertEqual(resp.status_code, 401)
        resp = self.client.delete("/playlist/music/" + str(uuid.uuid4()) + ".ogg")
        self.assertEqual(resp.status_code, 401)

    def testFailingLogin(self):
        resp = self.client.get("/auth/login/")
        self.assertEqual(resp.status_code, 401)
        self.assertNotIn("Set-Cookie", resp.headers)

        resp = self.client.post("/auth/login/")
        self.assertEqual(resp.status_code, 401)
        self.assertNotIn("Set-Cookie", resp.headers)

    def testLogin(self):
        resp = self.client.post("/auth/login/", environ_base={"REMOTE_USER": "xyz"})
        self.assertEqual(resp.status_code, 200)
        response_data = json.loads(resp.data)
        self.assertIn("token", response_data)
        self.assertRegex(response_data["token"], r"([a-zA-Z0-9_-]+\.){2}[a-zA-Z0-9_-]+")


class PlaylistAPITestCase(unittest.TestCase):
    @mock.patch(
        "klangbecken.api.JWTAuthorizationMiddleware", lambda app, *args, **kwargs: app
    )
    def setUp(self):
        from klangbecken.api import klangbecken_api
        from klangbecken.playlist import FileAddition, MetadataChange

        self.upload_analyzer = mock.Mock(
            return_value=[
                FileAddition("testfile"),
                MetadataChange("testkey", "testvalue"),
            ]
        )
        self.update_analyzer = mock.Mock(return_value=["UpdateChange"])
        self.processor = mock.MagicMock()

        app = klangbecken_api(
            "very secret",
            "data_dir",
            "player.sock",
            upload_analyzers=[self.upload_analyzer],
            update_analyzers=[self.update_analyzer],
            processors=[self.processor],
        )
        self.client = Client(app)

    @mock.patch("werkzeug.datastructures.FileStorage.save", lambda *args: None)
    @mock.patch("os.remove", lambda fname: None)
    def testUpload(self):
        from klangbecken.playlist import FileAddition, MetadataChange

        # Correct upload
        resp = self.client.post(
            "/playlist/music/", data={"file": (io.BytesIO(b"testcontent"), "test.mp3")}
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        fileId = list(data.keys())[0]
        self.assertEqual(fileId, str(uuid.UUID(fileId)))
        self.assertEqual(
            list(data.values())[0],
            {"testkey": "testvalue", "original_filename": "test.mp3", "uploader": ""},
        )
        self.update_analyzer.assert_not_called()
        self.upload_analyzer.assert_called_once()
        args = self.upload_analyzer.call_args[0]
        self.assertEqual(args[0], "music")
        self.assertEqual(args[1], fileId)
        self.assertEqual(args[2], "mp3")
        self.assertTrue(isinstance(args[3], str))
        self.assertTrue(args[3].startswith("data_dir/upload/"))

        self.processor.assert_called_once_with(
            "data_dir",
            "music",
            fileId,
            "mp3",
            [
                FileAddition("testfile"),
                MetadataChange("testkey", "testvalue"),
                MetadataChange("original_filename", "test.mp3"),
                MetadataChange("uploader", ""),
            ],
        )

        self.upload_analyzer.reset_mock()
        self.processor.reset_mock()

    def testUpdate(self):
        # Update weight correctly
        fileId = str(uuid.uuid4())
        resp = self.client.put(
            "/playlist/music/" + fileId + ".mp3",
            data=json.dumps({"weight": 4}),
            content_type="text/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.update_analyzer.assert_called_once_with(
            "music", fileId, "mp3", {"weight": 4}
        )
        self.upload_analyzer.assert_not_called()
        self.processor.assert_called_once_with(
            "data_dir", "music", fileId, "mp3", ["UpdateChange"]
        )
        self.update_analyzer.reset_mock()
        self.processor.reset_mock()

        # Update artist and title correctly
        resp = self.client.put(
            "/playlist/music/" + fileId + ".mp3",
            data=json.dumps({"artist": "A", "title": "B"}),
            content_type="text/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.update_analyzer.assert_called_once_with(
            "music", fileId, "mp3", {"artist": "A", "title": "B"}
        )
        self.processor.assert_called_once_with(
            "data_dir", "music", fileId, "mp3", ["UpdateChange"]
        )
        self.update_analyzer.reset_mock()
        self.processor.reset_mock()

        # Update with invalid json format
        resp = self.client.put(
            "/playlist/music/" + fileId + ".mp3",
            data='{ a: " }',
            content_type="text/json",
        )
        self.assertEqual(resp.status_code, 415)
        self.assertIn(b"invalid JSON", resp.data)
        self.update_analyzer.assert_not_called()

        # Update with invalid unicode format
        resp = self.client.put(
            "/playlist/music/" + fileId + ".mp3", data=b"\xFF", content_type="text/json"
        )
        self.assertEqual(resp.status_code, 415)
        self.assertIn(b"invalid UTF-8 data", resp.data)
        self.update_analyzer.assert_not_called()

    def testDelete(self):
        from klangbecken.playlist import FileDeletion

        fileId = str(uuid.uuid4())
        resp = self.client.delete("/playlist/music/" + fileId + ".mp3")
        self.assertEqual(resp.status_code, 200)
        self.update_analyzer.assert_not_called()
        self.upload_analyzer.assert_not_called()
        self.processor.assert_called_once_with(
            "data_dir", "music", fileId, "mp3", [FileDeletion()]
        )
        self.upload_analyzer.reset_mock()
        self.processor.reset_mock()


class PlayerAPITestCase(unittest.TestCase):
    def setUp(self):
        from klangbecken.api import player_api

        self.liquidsoap_client = mock.MagicMock(name="LiquidsoapClient")
        self.liquidsoap_client_class = mock.Mock(return_value=self.liquidsoap_client)
        self.liquidsoap_client.__enter__ = mock.Mock(
            return_value=self.liquidsoap_client
        )
        self.tempdir = tempfile.mkdtemp()
        app = player_api("inexistent.sock", self.tempdir)
        os.mkdir(os.path.join(self.tempdir, "music"))
        with open(os.path.join(self.tempdir, "music", "titi.mp3"), "w"):
            pass
        self.client = Client(app)

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def testInfo(self):
        self.liquidsoap_client.info = mock.Mock(return_value="info")

        with mock.patch(
            "klangbecken.api.LiquidsoapClient", self.liquidsoap_client_class
        ):
            resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"info", resp.data)
        self.liquidsoap_client.info.assert_called_once_with()

    def testReloadPlaylist(self):
        self.liquidsoap_client.command = mock.Mock(return_value="")

        with mock.patch(
            "klangbecken.api.LiquidsoapClient", self.liquidsoap_client_class
        ):
            resp = self.client.post("/reload/jingles")
        self.assertEqual(resp.status_code, 200)
        self.liquidsoap_client.command.assert_called_once_with("jingles.reload")

    def testQueueListCorrect(self):
        self.liquidsoap_client.queue = mock.Mock(return_value="queue")
        with mock.patch(
            "klangbecken.api.LiquidsoapClient", self.liquidsoap_client_class
        ):
            resp = self.client.get("/queue/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"queue", resp.data)
        self.liquidsoap_client.queue.assert_called_once_with()

    def testQueuePushCorrect(self):
        self.liquidsoap_client.push = mock.Mock(return_value="my_id")
        with mock.patch(
            "klangbecken.api.LiquidsoapClient", self.liquidsoap_client_class
        ):
            resp = self.client.post(
                "/queue/", data=json.dumps({"filename": "music/titi.mp3"})
            )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data["queue_id"], "my_id")
        self.liquidsoap_client.push.assert_called_once_with(
            os.path.join(self.tempdir, "music", "titi.mp3")
        )

    def testQueuePushIncorrect(self):
        self.liquidsoap_client.push = mock.Mock(return_value="my_track_id")
        with mock.patch(
            "klangbecken.api.LiquidsoapClient", self.liquidsoap_client_class
        ):
            resp = self.client.post(
                "/queue/", data=json.dumps({"filename": "music/tata.mp3"})
            )
        self.assertEqual(resp.status_code, 404)
        self.liquidsoap_client.push.assert_not_called()

        with mock.patch(
            "klangbecken.api.LiquidsoapClient", self.liquidsoap_client_class
        ):
            resp = self.client.post(
                "/queue/", data=json.dumps({"filename": "music/titi.abc"})
            )
        self.assertEqual(resp.status_code, 422)
        self.liquidsoap_client.push.assert_not_called()

        with mock.patch(
            "klangbecken.api.LiquidsoapClient", self.liquidsoap_client_class
        ):
            resp = self.client.post(
                "/queue/", data=json.dumps({"file": "music/titi.mp3"})
            )
        self.assertEqual(resp.status_code, 422)
        self.liquidsoap_client.push.assert_not_called()

    def testQueueDelete(self):
        with mock.patch(
            "klangbecken.api.LiquidsoapClient", self.liquidsoap_client_class
        ):
            resp = self.client.delete("/queue/15")
        self.assertEqual(resp.status_code, 200)
        self.liquidsoap_client.delete.assert_called_once_with("15")
