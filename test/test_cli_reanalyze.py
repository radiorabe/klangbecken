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
        from klangbecken.cli import import_cmd
        from klangbecken.utils import _check_data_dir

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
                print(err, file=sys.stderr)
                raise (RuntimeError("Command execution failed"))

        for filename in os.listdir(os.path.join(self.data_dir, "music")):
            mutagenFile = File(
                os.path.join(self.data_dir, "music", filename), easy=True
            )
            del mutagenFile["cue_in"]
            del mutagenFile["cue_out"]
            del mutagenFile["track_gain"]
            mutagenFile.save()

    def tearDown(self):
        shutil.rmtree(self.data_dir)

    def testSingleFileMocked(self):
        from klangbecken.cli import reanalyze_cmd

        for filename in os.listdir(os.path.join(self.data_dir, "music")):
            mutagenFile = File(
                os.path.join(self.data_dir, "music", filename), easy=True
            )
            self.assertNotIn("cue_in", mutagenFile)
            self.assertNotIn("cue_out", mutagenFile)
            self.assertNotIn("track_gain", mutagenFile)

        # mocked call: single file
        with mock.patch(
            "klangbecken.cli.ffmpeg_audio_analyzer", return_value=[("key", "val")]
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
            self.data_dir, "music", *filename.split("."), [("key", "val")]
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

    def testAllFilesMocked(self):
        from klangbecken.cli import reanalyze_cmd

        with mock.patch("klangbecken.cli.ffmpeg_audio_analyzer") as analyzer:
            with mock.patch(
                "klangbecken.cli.DEFAULT_PROCESSORS", [mock.Mock()]
            ) as processors:
                with capture(reanalyze_cmd, self.data_dir, [], True, True):
                    with mock.patch(
                        "sys.argv", ["", "reanalyze", "-d", self.data_dir, "--all"]
                    ):
                        pass

        self.assertEqual(analyzer.call_count, self.file_count)
        self.assertEqual(processors[0].call_count, self.file_count)
