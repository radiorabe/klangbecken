import json
import os
import shutil
import tempfile
import unittest
import uuid

from werkzeug.test import Client
from werkzeug.wrappers import BaseResponse

from .utils import capture


class DevServerStartupTestCase(unittest.TestCase):
    def setUp(self):
        self.current_path = os.path.dirname(os.path.realpath(__file__))
        self.tempdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def testNoFFmpegWarning(self):
        from klangbecken.api import development_server
        from klangbecken.cli import init_cmd

        init_cmd(self.tempdir)
        with capture(development_server, self.tempdir, "player.sock") as (
            out,
            err,
            ret,
        ):
            self.assertNotIn("WARNING", out)

    def testDirStructure(self):
        from klangbecken.api import development_server
        from klangbecken.cli import init_cmd

        self.assertFalse(os.path.isdir(os.path.join(self.tempdir, "music")))

        with self.assertRaises(Exception):
            development_server(self.tempdir, "secret")

        init_cmd(self.tempdir)
        development_server(self.tempdir, "secret")
        self.assertTrue(os.path.isdir(os.path.join(self.tempdir, "music")))

        with open(os.path.join(self.tempdir, "music", "abc.txt"), "w"):
            pass

        development_server(self.tempdir, "secret")
        self.assertTrue(os.path.isdir(os.path.join(self.tempdir, "music")))
        self.assertTrue(os.path.isfile(os.path.join(self.tempdir, "music", "abc.txt")))


class DevServerTestCase(unittest.TestCase):
    def setUp(self):
        from klangbecken.api import development_server
        from klangbecken.cli import init_cmd

        self.current_path = os.path.dirname(os.path.realpath(__file__))
        self.tempdir = tempfile.mkdtemp()
        init_cmd(self.tempdir)
        app = development_server(self.tempdir, "secret")
        self.client = Client(app, BaseResponse)

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def testIndexHtml(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Welcome", resp.data)
        self.assertIn(b"Klangbecken", resp.data)
        resp.close()

    def testApi(self):
        # Login
        resp = self.client.post("/api/auth/login/")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIn("token", data)
        token = data["token"]
        resp.close()

        # Upload
        path = os.path.join(self.current_path, "audio", "sine-unicode-jointstereo.mp3")
        with open(path, "rb") as f:
            resp = self.client.post(
                "/api/playlist/music/",
                data={"file": (f, "sine-unicode-jointstereo.mp3")},
                headers=[("Authorization", f"Bearer {token}")],
            )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        fileId = list(data.keys())[0]
        self.assertEqual(fileId, str(uuid.UUID(fileId)))
        expected = {
            "original_filename": "sine-unicode-jointstereo.mp3",
            "length": 5.0,
            "album": "Sine Album 👌👍🖖",
            "title": "Sine Title éàè",
            "artist": "Sine Artist öäü",
            "ext": "mp3",
            "weight": 1,
            "playlist": "music",
            "id": fileId,
        }
        self.assertLessEqual(set(expected.items()), set(data[fileId].items()))
        resp.close()

        # Update
        resp = self.client.put(
            "/api/playlist/music/" + fileId + ".mp3",
            data=json.dumps({"weight": 4}),
            content_type="text/json",
            headers=[("Authorization", f"Bearer {token}")],
        )
        self.assertEqual(resp.status_code, 200)
        resp.close()

        # Get file
        resp = self.client.get("/data/music/" + fileId + ".mp3")
        self.assertEqual(resp.status_code, 200)
        resp.close()

        # Get index.json
        resp = self.client.get("/data/index.json")
        self.assertEqual(resp.status_code, 200)
        resp.close()

        # Delete file
        resp = self.client.delete(
            "/api/playlist/music/" + fileId + ".mp3",
            headers=[("Authorization", f"Bearer {token}")],
        )
        self.assertEqual(resp.status_code, 200)
        resp.close()

        # Verify that we are logged out
        resp = self.client.post("/api/playlist/music/")
        self.assertEqual(resp.status_code, 401)
        resp.close()
