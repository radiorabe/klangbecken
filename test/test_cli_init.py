import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from .utils import capture


class InitCmdTestCase(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tempdir)

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

    def testDataDirCheckOnly(self):
        from klangbecken.cli import _check_data_dir
        from klangbecken.settings import PLAYLISTS

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
        from klangbecken.cli import _check_data_dir
        from klangbecken.settings import PLAYLISTS

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
