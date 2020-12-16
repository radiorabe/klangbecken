import datetime
import json
import os
import shutil
import tempfile
import unittest

import mock

from .utils import capture


class ImporterTestCase(unittest.TestCase):
    def setUp(self):
        from klangbecken import _check_data_dir

        self.current_path = os.path.dirname(os.path.realpath(__file__))
        self.tempdir = tempfile.mkdtemp()
        self.music_dir = os.path.join(self.tempdir, "music")
        self.jingles_dir = os.path.join(self.tempdir, "jingles")
        _check_data_dir(self.tempdir, create=True)

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def testImport(self):
        from klangbecken import import_cmd

        audio_path = os.path.join(self.current_path, "audio")
        audio1_path = os.path.join(audio_path, "sine-unicode.flac")
        audio2_path = os.path.join(audio_path, "padded.ogg")
        audio1_mtime = datetime.datetime.fromtimestamp(os.stat(audio1_path).st_mtime)

        # Import nothing -> usage
        args = [self.tempdir, "music", [], True]
        with self.assertRaises(SystemExit) as cm:
            with capture(import_cmd, *args) as (out, err, ret):
                pass

        # Import one file
        args = [self.tempdir, "music", [audio1_path], True]
        with self.assertRaises(SystemExit) as cm:
            with capture(import_cmd, *args) as (out, err, ret):
                self.assertIn("Successfully imported 1 of 1 files.", out)
        self.assertEqual(cm.exception.code, 0)

        files = [
            f
            for f in os.listdir(self.music_dir)
            if os.path.isfile(os.path.join(self.music_dir, f))
        ]
        self.assertEqual(len(files), 1)
        with open(os.path.join(self.tempdir, "index.json")) as file:
            data = json.load(file)
            self.assertEqual(len(data.keys()), 1)
            ts = list(data.values())[0]["import_timestamp"]
            ts = datetime.datetime.fromisoformat(ts)
            self.assertTrue(abs(ts - audio1_mtime) < datetime.timedelta(seconds=1))
            self.assertEqual(
                list(data.values())[0]["original_filename"], "sine-unicode.flac"
            )

        # Import two file
        args = [self.tempdir, "music", [audio1_path, audio2_path], True]
        with self.assertRaises(SystemExit) as cm:
            with capture(import_cmd, *args) as (out, err, ret):
                self.assertIn("Successfully imported 2 of 2 files.", out)
        self.assertEqual(cm.exception.code, 0)

        files = [
            f
            for f in os.listdir(self.music_dir)  # pragma: no cover
            if os.path.isfile(os.path.join(self.music_dir, f))
        ]
        self.assertEqual(len(files), 3)
        with open(os.path.join(self.tempdir, "index.json")) as file:
            self.assertEqual(len(json.load(file).keys()), 3)

        # Try importing inexistent file
        args = [self.tempdir, "music", [audio1_path, "inexistent"], True]
        with self.assertRaises(SystemExit) as cm:
            with capture(import_cmd, *args) as (out, err, ret):
                self.assertIn("Successfully imported 1 of 2 files.", out)
                self.assertIn("WARNING", err)
        self.assertEqual(cm.exception.code, 1)

        # Try importing into inexistent playlist
        args = [self.tempdir, "nonexistent", [audio1_path], True]
        with self.assertRaises(SystemExit) as cm:
            with capture(import_cmd, *args) as (out, err, ret):
                self.assertEqual(out.strip(), "")
                self.assertIn("ERROR", err)
        self.assertEqual(cm.exception.code, 1)

        # Try importing into inexistent data dir
        args = [self.tempdir, "inexistent", [audio1_path], True]
        with self.assertRaises(SystemExit) as cm:
            with capture(import_cmd, *args) as (out, err, ret):
                self.assertEqual(out.strip(), "")
                self.assertIn("ERROR", err)
        self.assertEqual(cm.exception.code, 1)

        path = os.path.join(self.tempdir, "file.wmv")
        with open(path, "w"):
            pass

        # Try importing unsupported file type
        args = [self.tempdir, "music", [path], True]
        with self.assertRaises(SystemExit) as cm:
            with capture(import_cmd, *args) as (out, err, ret):
                self.assertIn("Successfully imported 0 of 1 files.", out)
                self.assertIn("WARNING", err)
        self.assertEqual(cm.exception.code, 1)

    @mock.patch("klangbecken.input", return_value="y")
    def testImportInteractiveYes(self, input):
        from klangbecken import import_cmd

        audio_path = os.path.join(self.current_path, "audio")
        audio1_path = os.path.join(audio_path, "sine-unicode.flac")

        args = [self.tempdir, "music", [audio1_path], False]
        with self.assertRaises(SystemExit) as cm:
            with capture(import_cmd, *args) as (out, err, ret):
                self.assertIn("Successfully analyzed 1 of 1 files.", out)
                self.assertIn("Successfully imported 1 of 1 files.", out)
                music_dir = os.path.join(self.tempdir, "music")
                file_count = len(os.listdir(music_dir))
                self.assertEqual(file_count, 1)
        self.assertEqual(cm.exception.code, 0)

    @mock.patch("klangbecken.input", return_value="n")
    def testImportInteractiveNo(self, input):
        from klangbecken import import_cmd

        audio_path = os.path.join(self.current_path, "audio")
        audio1_path = os.path.join(audio_path, "sine-unicode.flac")

        args = [self.tempdir, "music", [audio1_path], False]

        with self.assertRaises(SystemExit) as cm:
            with capture(import_cmd, *args) as (out, err, ret):
                self.assertIn("Successfully analyzed 1 of 1 files.", out)
                self.assertIn("Successfully imported 0 of 1 files.", out)
                music_dir = os.path.join(self.tempdir, "music")
                file_count = len(os.listdir(music_dir))
                self.assertEqual(file_count, 0)
        self.assertEqual(cm.exception.code, 1)
