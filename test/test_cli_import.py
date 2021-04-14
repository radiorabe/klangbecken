import datetime
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import mutagen

from .utils import capture


class ImporterTestCase(unittest.TestCase):
    def setUp(self):
        from klangbecken.cli import _check_data_dir

        self.current_path = os.path.dirname(os.path.realpath(__file__))
        self.tempdir = tempfile.mkdtemp()
        self.music_dir = os.path.join(self.tempdir, "music")
        self.jingles_dir = os.path.join(self.tempdir, "jingles")
        _check_data_dir(self.tempdir, create=True)

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def testImport(self):
        from klangbecken.cli import import_cmd, main

        audio_path = os.path.join(self.current_path, "audio")
        audio1_path = os.path.join(audio_path, "sine-unicode-stereo.mp3")
        audio2_path = os.path.join(audio_path, "padded-stereo.mp3")
        audio1_mtime = datetime.datetime.fromtimestamp(os.stat(audio1_path).st_mtime)

        # Import nothing -> usage
        cmd = f"klangbecken import -d {self.tempdir} --yes --mtime music"
        with mock.patch("sys.argv", cmd.split()):
            with self.assertRaises(SystemExit) as cm:
                with capture(main) as (out, err, ret):
                    pass
        self.assertTrue(hasattr(cm.exception, "usage"))

        # Import one file
        cmd = f"klangbecken import -d {self.tempdir} -y -m music {audio1_path}"
        with self.assertRaises(SystemExit) as cm:
            with mock.patch("sys.argv", cmd.split()):
                with capture(main) as (out, err, ret):
                    pass
        # print(out, err, ret)
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
            import_timestamp = list(data.values())[0]["import_timestamp"]
            self.assertLess(
                (audio1_mtime - datetime.timedelta(seconds=1)).isoformat(),
                import_timestamp,
            )
            self.assertGreater(
                (audio1_mtime + datetime.timedelta(seconds=1)).isoformat(),
                import_timestamp,
            )
            self.assertEqual(
                list(data.values())[0]["original_filename"], "sine-unicode-stereo.mp3"
            )

        # Import two file
        args = [self.tempdir, "music", [audio1_path, audio2_path], True]
        with self.assertRaises(SystemExit) as cm:
            with capture(import_cmd, *args) as (out, err, ret):
                self.assertIn("Successfully imported 2 of 2 files.", out)
        self.assertEqual(cm.exception.code, 0)

        files = [
            f
            for f in os.listdir(self.music_dir)
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

    def testImportWithMetadataFile(self):
        from klangbecken.cli import main

        audio_path = os.path.join(self.current_path, "audio")
        audio1_path = os.path.join(audio_path, "sine-unicode-stereo.mp3")
        audio2_path = os.path.join(audio_path, "padded-stereo.mp3")

        metadata_path = os.path.join(self.tempdir, "metadata.json")
        with open(metadata_path, "w") as f:
            json.dump({audio1_path: {"artist": "artist", "title": "title"}}, f)

        # Import one file with additional metadata
        cmd = (
            f"klangbecken import -d {self.tempdir} -y -m -M {metadata_path} "
            f"music {audio1_path}"
        )
        with self.assertRaises(SystemExit) as cm:
            with mock.patch("sys.argv", cmd.split()):
                with capture(main) as (out, err, ret):
                    pass
        self.assertIn("Successfully imported 1 of 1 files.", out)
        self.assertEqual(cm.exception.code, 0)

        imported_path = os.listdir(os.path.join(self.tempdir, "music"))[0]
        imported_path = os.path.join(self.tempdir, "music", imported_path)
        mutagen_file = mutagen.File(imported_path, easy=True)
        self.assertEqual(mutagen_file["artist"][0], "artist")

        # Try importing one file without additional metadata
        cmd = (
            f"klangbecken import -d {self.tempdir} -y -m -M {metadata_path} "
            f"music {audio2_path}"
        )
        with self.assertRaises(SystemExit) as cm:
            with mock.patch("sys.argv", cmd.split()):
                with capture(main) as (out, err, ret):
                    pass

        self.assertIn("Successfully imported 0 of 1 files.", out)
        self.assertIn("Ignoring", out)
        self.assertEqual(cm.exception.code, 1)

    @mock.patch("klangbecken.cli.input", return_value="y")
    def testImportInteractiveYes(self, input):
        from klangbecken.cli import import_cmd

        audio_path = os.path.join(self.current_path, "audio")
        audio1_path = os.path.join(audio_path, "sine-unicode-stereo.mp3")

        args = [self.tempdir, "music", [audio1_path], False]
        with self.assertRaises(SystemExit) as cm:
            with capture(import_cmd, *args) as (out, err, ret):
                self.assertIn("Successfully analyzed 1 of 1 files.", out)
                self.assertIn("Successfully imported 1 of 1 files.", out)
                music_dir = os.path.join(self.tempdir, "music")
                file_count = len(os.listdir(music_dir))
                self.assertEqual(file_count, 1)
        self.assertEqual(cm.exception.code, 0)

    @mock.patch("klangbecken.cli.input", return_value="n")
    def testImportInteractiveNo(self, input):
        from klangbecken.cli import import_cmd

        audio_path = os.path.join(self.current_path, "audio")
        audio1_path = os.path.join(audio_path, "sine-unicode-stereo.mp3")

        args = [self.tempdir, "music", [audio1_path], False]

        with self.assertRaises(SystemExit) as cm:
            with capture(import_cmd, *args) as (out, err, ret):
                self.assertIn("Successfully analyzed 1 of 1 files.", out)
                self.assertIn("Successfully imported 0 of 1 files.", out)
                music_dir = os.path.join(self.tempdir, "music")
                file_count = len(os.listdir(music_dir))
                self.assertEqual(file_count, 0)
        self.assertEqual(cm.exception.code, 1)
