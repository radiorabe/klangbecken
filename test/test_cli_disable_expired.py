import datetime
import os
import shutil
import sys
import tempfile
import unittest

from .utils import capture


class DisableExpiredTestCase(unittest.TestCase):
    def setUp(self):
        from klangbecken.cli import _check_data_dir, import_cmd

        self.current_path = os.path.dirname(os.path.realpath(__file__))
        self.tempdir = tempfile.mkdtemp()
        self.jingles_dir = os.path.join(self.tempdir, "jingles")
        self.jingles_playlist = os.path.join(self.tempdir, "jingles.m3u")
        _check_data_dir(self.tempdir, create=True)

        # Correctly import a couple of files
        files = [
            os.path.join(self.current_path, "audio", "padded" + ext)
            for ext in "-stereo.mp3 -jointstereo.mp3 -end-stereo.mp3".split()
        ]
        try:
            args = [self.tempdir, "jingles", files, True]
            with capture(import_cmd, *args) as (out, err, ret):
                pass
        except SystemExit as e:
            if e.code != 0:
                print(e, file=sys.stderr)
                raise (RuntimeError("Command execution failed"))

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def testDisableExpired(self):
        from klangbecken.cli import main
        from klangbecken.playlist import DEFAULT_PROCESSORS, MetadataChange

        track1, track2, track3 = os.listdir(self.jingles_dir)

        # "empty" run
        argv, sys.argv = sys.argv, ["", "disable-expired", "-d", self.tempdir]
        try:
            with capture(main) as (out, err, ret):
                self.assertEqual(err.strip(), "")
        finally:
            sys.arv = argv

        with open(self.jingles_playlist) as f:
            lines = f.readlines()
        self.assertEqual(len(lines), 3)

        # modify expiration dates
        now = datetime.datetime.now()
        past = now - datetime.timedelta(hours=1)
        future = now + datetime.timedelta(hours=1)
        for processor in DEFAULT_PROCESSORS:
            processor(
                self.tempdir,
                "jingles",
                *track1.split("."),
                [MetadataChange("expiration", past.astimezone().isoformat())],
            )
            processor(
                self.tempdir,
                "jingles",
                *track2.split("."),
                [MetadataChange("expiration", future.astimezone().isoformat())],
            )

        # run for real
        argv, sys.argv = sys.argv, ["", "disable-expired", "-d", self.tempdir]
        try:
            with capture(main) as (out, err, ret):
                self.assertEqual(err.strip(), "")
        finally:
            sys.arv = argv

        self.assertIn(track1, out)
        with open(self.jingles_playlist) as f:
            lines = [line.strip() for line in f.readlines()]
        self.assertEqual(len(lines), 2)
        for line in lines:
            self.assertNotIn(track1, line)
        self.assertNotIn(f"jingles/{track1}", lines)
        self.assertIn(f"jingles/{track2}", lines)
        self.assertIn(f"jingles/{track3}", lines)
