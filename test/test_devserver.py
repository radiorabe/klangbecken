import json
import os
import shutil
import tempfile
import unittest
import uuid
from unittest import mock

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


class StandaloneWebApplicationTestCase(unittest.TestCase):
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
        path = os.path.join(self.current_path, "audio", "sine-unicode.flac")
        with open(path, "rb") as f:
            resp = self.client.post(
                "/api/playlist/music/",
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
            "/api/playlist/music/" + fileId + ".flac",
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
        #
        # # Put file in prio list
        # resp = self.client.post(
        #     "/api/player/queue/",
        #     data=json.dumps({"filename": "music/" + fileId + ".flac"}),
        #     content_type="text/json",
        #     headers=[("Authorization", f"Bearer {token}")],
        # )
        # print(resp.data)
        # self.assertEqual(resp.status_code, 200)
        # resp.close()

        # Get index.json
        resp = self.client.get("/data/index.json")
        self.assertEqual(resp.status_code, 200)
        resp.close()

        # Delete file
        resp = self.client.delete(
            "/api/playlist/music/" + fileId + ".flac",
            headers=[("Authorization", f"Bearer {token}")],
        )
        self.assertEqual(resp.status_code, 200)
        resp.close()

        # Verify that we are logged out
        resp = self.client.post("/api/playlist/music/")
        self.assertEqual(resp.status_code, 401)
        resp.close()


class DataDirCreatorTestCase(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def testDataDirCheckOnly(self):
        from klangbecken.settings import PLAYLISTS
        from klangbecken.utils import _check_data_dir

        for playlist in PLAYLISTS + ("log",):
            path = os.path.join(self.tempdir, playlist)
            with self.assertRaises(Exception) as cm:
                _check_data_dir(self.tempdir, False)
            self.assertIn("Directory", cm.exception.args[0])
            self.assertIn("does not exist", cm.exception.args[0])
            os.mkdir(path)

        for playlist in PLAYLISTS:
            path = os.path.join(self.tempdir, playlist + ".m3u")
            with self.assertRaises(Exception) as cm:
                _check_data_dir(self.tempdir, False)
            self.assertIn("Playlist", cm.exception.args[0])
            self.assertIn("does not exist", cm.exception.args[0])
            with open(path, "a"):
                pass

        with self.assertRaises(Exception) as cm:
            _check_data_dir(self.tempdir, False)
        self.assertIn("File", cm.exception.args[0])
        self.assertIn("does not exist", cm.exception.args[0])

        with open(os.path.join(self.tempdir, "index.json"), "w"):
            pass

        _check_data_dir(self.tempdir, False)

    def testDataDirCreation(self):
        from klangbecken.settings import PLAYLISTS
        from klangbecken.utils import _check_data_dir

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

    def testInitCmd(self):
        from klangbecken.cli import main

        path = os.path.join(self.tempdir, "data")
        with mock.patch("sys.argv", f"klangbecken init -d {path}".split()):
            main()
        self.assertTrue(os.path.exists(path))

        with open(os.path.join(path, "file"), "w"):
            pass

        with self.assertRaises(SystemExit):
            with mock.patch("sys.argv", f"klangbecken init -d {path}".split()):
                with capture(main) as (out, err, ret):
                    self.assertIn("ERROR", err)
                    self.assertIn("not empty", err)

        path = os.path.join(path, "file")

        with self.assertRaises(SystemExit):
            with mock.patch("sys.argv", f"klangbecken init -d {path}".split()):
                with capture(main) as (out, err, ret):
                    self.assertIn("ERROR", err)
                    self.assertIn("not a directory", err)
