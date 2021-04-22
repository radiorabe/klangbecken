import csv
import datetime
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

from mutagen import File

from .utils import capture


class PlaylogCmdTestCase(unittest.TestCase):
    def setUp(self):
        from klangbecken.cli import _check_data_dir, import_cmd

        self.current_path = os.path.dirname(os.path.realpath(__file__))
        self.data_dir = tempfile.mkdtemp()
        _check_data_dir(self.data_dir, create=True)

        # Correctly import a couple of files
        files = [
            os.path.join(self.current_path, "audio", "padded" + ext)
            for ext in "-jointstereo.mp3 -stereo.mp3".split()
        ]
        try:
            args = [self.data_dir, "music", files, True]
            with capture(import_cmd, *args) as (out, err, ret):
                pass
        except SystemExit as e:
            if e.code != 0:
                print(err, file=sys.stderr)
                raise (RuntimeError("Command execution failed"))

    def tearDown(self):
        shutil.rmtree(self.data_dir)

    def testPlayLog(self):
        from klangbecken.cli import main, playlog_cmd

        now = datetime.datetime(2018, 4, 28).astimezone()

        filename = os.listdir(os.path.join(self.data_dir, "music"))[0]
        path = os.path.join(self.data_dir, "music", filename)

        id_file = os.path.join(self.data_dir, "id.txt")

        with mock.patch("klangbecken.cli.datetime") as dt:
            with mock.patch(
                "klangbecken.cli.EXTERNAL_PLAY_LOGGER", "echo {id} >> " + id_file
            ):
                dt.datetime.now = mock.Mock(return_value=now)
                # First call
                playlog_cmd(self.data_dir, path)

        with open(os.path.join(self.data_dir, "index.json")) as f:
            cache_data = json.load(f)
        entry = cache_data[filename.split(".")[0]]

        self.assertEqual(entry["last_play"], now.isoformat())
        self.assertEqual(entry["play_count"], 1)

        mutagenFile = File(path, easy=True)
        self.assertEqual(mutagenFile["last_play_epoch"][0], str(now.timestamp()))

        with open(os.path.join(self.data_dir, "log", "2018-04.csv")) as f:
            reader = csv.DictReader(f)
            entry = next(reader)

        self.assertEqual(entry["last_play"], now.isoformat())
        self.assertEqual(entry["play_count"], "1")

        with open(id_file) as f:
            self.assertEqual(f.read().strip(), filename.split(".")[0])

        now = now + datetime.timedelta(days=1)
        with mock.patch("klangbecken.cli.datetime") as dt:
            with mock.patch("sys.argv", ["", "playlog", "-d", self.data_dir, path]):
                dt.datetime.now = mock.Mock(return_value=now)
                # Second call with no external play logger, now via the main function
                main()

        with open(os.path.join(self.data_dir, "index.json")) as f:
            cache_data = json.load(f)
        entry = cache_data[filename.split(".")[0]]

        self.assertEqual(entry["last_play"], now.isoformat())
        self.assertEqual(entry["play_count"], 2)

        with open(os.path.join(self.data_dir, "log", "2018-04.csv")) as f:
            reader = csv.DictReader(f)
            self.assertEqual(len(list(reader)), 2)

        with open(id_file) as f:
            self.assertEqual(f.read().strip(), filename.split(".")[0])
