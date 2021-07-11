import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

from mutagen import File

from .utils import capture


class ReanalyzeCmdTestCase(unittest.TestCase):
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
        self.file_count = len(files)

        try:
            args = [self.data_dir, "music", files, True]
            with capture(import_cmd, *args) as (out, err, ret):
                pass
        except SystemExit as e:
            if e.code != 0:
                print(e, file=sys.stderr)
                raise (RuntimeError("Command execution failed"))

        for filename in os.listdir(os.path.join(self.data_dir, "music")):
            mutagenFile = File(
                os.path.join(self.data_dir, "music", filename), easy=True
            )
            mutagenFile["cue_in"] = "0.0"
            mutagenFile["cue_out"] = "5.0"
            mutagenFile["track_gain"] = "-3.0 dB"
            mutagenFile.save()

        with open(os.path.join(self.data_dir, "index.json"), "r+") as f:
            data = json.load(f)
            for entry in data.values():
                entry["cue_in"] = 0.0
                entry["cue_out"] = 5.0
                entry["track_gain"] = "-3.0 dB"
            f.seek(0)
            f.truncate()
            json.dump(data, f)

    def tearDown(self):
        shutil.rmtree(self.data_dir)

    def testSingleFileMocked(self):
        from klangbecken.cli import reanalyze_cmd
        from klangbecken.playlist import MetadataChange

        filename = os.listdir(os.path.join(self.data_dir, "music"))[0]

        # mocked call: single file
        with mock.patch(
            "klangbecken.cli.ffmpeg_audio_analyzer",
            return_value=[MetadataChange("cue_in", 3.0)],
        ) as analyzer:
            with mock.patch(
                "klangbecken.cli.DEFAULT_PROCESSORS", [mock.Mock()]
            ) as processors:
                with capture(
                    reanalyze_cmd, self.data_dir, [filename.split(".")[0]], False, True
                ):
                    pass

        analyzer.assert_called_once_with("music", *filename.split("."), mock.ANY)
        analyzer.reset_mock()
        processors[0].assert_called_once_with(
            self.data_dir,
            "music",
            *filename.split("."),
            [MetadataChange("cue_in", 3.0)],
        )

    def testSingleFile(self):
        from klangbecken.cli import main

        filename = os.listdir(os.path.join(self.data_dir, "music"))[0]
        file_id = filename.split(".")[0]

        with mock.patch(
            "sys.argv", ["", "reanalyze", "-d", self.data_dir, file_id, "--yes"]
        ):
            with capture(main):
                pass

        mutagenFile = File(os.path.join(self.data_dir, "music", filename), easy=True)
        self.assertIn("cue_in", mutagenFile)
        self.assertIn("cue_out", mutagenFile)
        self.assertIn("track_gain", mutagenFile)
        self.assertNotEqual(mutagenFile["cue_in"][0], "0.0")
        self.assertNotEqual(mutagenFile["cue_out"][0], "5.0")
        self.assertNotEqual(mutagenFile["track_gain"][0], "-3.0 dB")

        # failing analysis: overwrite file
        open(os.path.join(self.data_dir, "music", filename), "w").close()

        with mock.patch(
            "sys.argv", ["", "reanalyze", "-d", self.data_dir, file_id, "--yes"]
        ):
            with capture(main) as (out, err, ret):
                pass

        self.assertIn("FAILED: Cannot process audio data", out)
        self.assertIn(f"Failed Tracks (1):\n - music/{file_id}.mp3", out)

    def testAllFilesMocked(self):
        from klangbecken.cli import reanalyze_cmd
        from klangbecken.playlist import MetadataChange

        with mock.patch(
            "klangbecken.cli.DEFAULT_PROCESSORS", [mock.Mock()]
        ) as processors:
            with capture(reanalyze_cmd, self.data_dir, [], True, True):
                with mock.patch(
                    "sys.argv", ["", "reanalyze", "-d", self.data_dir, "--all"]
                ):
                    pass

        self.assertEqual(processors[0].call_count, self.file_count)
        changed_fields = {"cue_in", "cue_out", "track_gain"}
        for call_args in processors[0].call_args_list:
            changes = call_args[0][4]
            self.assertEqual(len(changes), 3)
            self.assertTrue(all(isinstance(c, MetadataChange) for c in changes))
            self.assertTrue(all(c.key in changed_fields for c in changes))
