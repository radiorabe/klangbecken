import json
import os
import shutil
import tempfile
import unittest
import uuid

from werkzeug.test import Client
from werkzeug.wrappers import BaseResponse

from .utils import capture


class StandaloneWebApplicationStartupTestCase(unittest.TestCase):
    def setUp(self):
        self.current_path = os.path.dirname(os.path.realpath(__file__))
        self.tempdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def testNoFFmpegWarning(self):
        from klangbecken import StandaloneWebApplication, init_cmd

        init_cmd(self.tempdir)
        with capture(StandaloneWebApplication, self.tempdir, "secret") as (
            out,
            err,
            ret,
        ):
            self.assertNotIn("WARNING", out)

    def testDirStructure(self):
        from klangbecken import StandaloneWebApplication, init_cmd

        self.assertFalse(os.path.isdir(os.path.join(self.tempdir, "music")))

        with self.assertRaises(Exception):
            StandaloneWebApplication(self.tempdir, "secret")

        init_cmd(self.tempdir)
        StandaloneWebApplication(self.tempdir, "secret")
        self.assertTrue(os.path.isdir(os.path.join(self.tempdir, "music")))

        with open(os.path.join(self.tempdir, "music", "abc.txt"), "w"):
            pass

        StandaloneWebApplication(self.tempdir, "secret")
        self.assertTrue(os.path.isdir(os.path.join(self.tempdir, "music")))
        self.assertTrue(os.path.isfile(os.path.join(self.tempdir, "music", "abc.txt")))


class StandaloneWebApplicationTestCase(unittest.TestCase):
    def setUp(self):
        from klangbecken import StandaloneWebApplication, init_cmd

        self.current_path = os.path.dirname(os.path.realpath(__file__))
        self.tempdir = tempfile.mkdtemp()
        init_cmd(self.tempdir)
        app = StandaloneWebApplication(self.tempdir, "secret")
        self.client = Client(app, BaseResponse)

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def testIndexHtml(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data.startswith(b"Welcome"))
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
        path = os.path.join(self.current_path, "audio", "sine-unicode.flac")
        with open(path, "rb") as f:
            resp = self.client.post(
                "/api/music/",
                data={"file": (f, "sine-unicode.flac")},
                headers=[("Authorization", f"Bearer {token}")],
            )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        fileId = list(data.keys())[0]
        self.assertEqual(fileId, str(uuid.UUID(fileId)))
        expected = {
            "original_filename": "sine-unicode.flac",
            "length": 5.0,
            "album": "Sine Album 👌👍🖖",
            "title": "Sine Title éàè",
            "artist": "Sine Artist öäü",
            "ext": "flac",
            "weight": 1,
            "playlist": "music",
            "id": fileId,
        }
        self.assertLessEqual(set(expected.items()), set(data[fileId].items()))
        resp.close()

        # Update
        resp = self.client.put(
            "/api/music/" + fileId + ".flac",
            data=json.dumps({"weight": 4}),
            content_type="text/json",
            headers=[("Authorization", f"Bearer {token}")],
        )
        self.assertEqual(resp.status_code, 200)
        resp.close()

        # Get file
        resp = self.client.get("/data/music/" + fileId + ".flac")
        self.assertEqual(resp.status_code, 200)
        resp.close()

        # Put file in prio list
        resp = self.client.post(
            "/api/playnext/",
            data=json.dumps({"file": "music/" + fileId + ".flac"}),
            content_type="text/json",
            headers=[("Authorization", f"Bearer {token}")],
        )
        self.assertEqual(resp.status_code, 200)
        resp.close()

        # Get index.json
        resp = self.client.get("/data/index.json")
        self.assertEqual(resp.status_code, 200)
        resp.close()

        # Delete file
        resp = self.client.delete(
            "/api/music/" + fileId + ".flac",
            headers=[("Authorization", f"Bearer {token}")],
        )
        self.assertEqual(resp.status_code, 200)
        resp.close()

        # Verify that we are logged out
        resp = self.client.post("/api/music/")
        self.assertEqual(resp.status_code, 401)
        resp.close()


class DataDirCreatorTestCase(unittest.TestCase):
    def setUp(self):
        self.current_path = os.path.dirname(os.path.realpath(__file__))
        self.tempdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def testDataDirCheckOnly(self):
        from klangbecken import _check_data_dir, PLAYLISTS

        for playlist in PLAYLISTS + ("prio",):
            path = os.path.join(self.tempdir, playlist)
            with self.assertRaises(Exception):
                _check_data_dir(self.tempdir, False)
            os.mkdir(path)

        for playlist in PLAYLISTS + ("prio",):
            path = os.path.join(self.tempdir, playlist + ".m3u")
            with self.assertRaises(Exception):
                _check_data_dir(self.tempdir, False)
            with open(path, "a"):
                pass
        with self.assertRaises(Exception):
            _check_data_dir(self.tempdir, False)

        with open(os.path.join(self.tempdir, "index.json"), "w"):
            pass

        os.mkdir(os.path.join(self.tempdir, "log"))

        _check_data_dir(self.tempdir, False)

    def testDataDirCreation(self):
        from klangbecken import _check_data_dir, PLAYLISTS

        _check_data_dir(self.tempdir, create=True)
        for playlist in PLAYLISTS:
            path = os.path.join(self.tempdir, playlist)
            self.assertTrue(os.path.isdir(path))
            path += ".m3u"
            self.assertTrue(os.path.isfile(path))

        path = os.path.join(self.tempdir, "index.json")
        self.assertTrue(os.path.isfile(path))
        with open(path) as f:
            self.assertEqual(json.load(f), {})
