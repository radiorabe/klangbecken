import io
import json
import os
import shutil
import tempfile
import unittest

from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import NotFound, UnprocessableEntity


class AnalyzersTestCase(unittest.TestCase):
    def setUp(self):
        self.current_path = os.path.dirname(os.path.realpath(__file__))
        fd, name = tempfile.mkstemp()
        os.write(fd, b"\0" * 1024)
        os.close(fd)
        self.invalid_file = name

    def tearDown(self):
        os.remove(self.invalid_file)

    def testUpdateAnalyzer(self):
        from klangbecken.playlist import MetadataChange, update_data_analyzer

        # Correct single update
        self.assertEqual(
            update_data_analyzer("playlist", "id", "ext", {"artist": "A"}),
            [MetadataChange("artist", "A")],
        )

        # Correct multiple updates
        changes = update_data_analyzer(
            "playlist", "id", "ext", {"artist": "A", "title": "Ø"}
        )
        self.assertEqual(len(changes), 2)
        self.assertTrue(MetadataChange("artist", "A") in changes)
        self.assertTrue(MetadataChange("title", "Ø") in changes)

        # Update not allowed property (original_filename)
        self.assertRaises(
            UnprocessableEntity,
            update_data_analyzer,
            "playlist",
            "id",
            "ext",
            {"original_filename": "test.mp3"},
        )

        # Update with wrong data format
        self.assertRaises(
            UnprocessableEntity,
            update_data_analyzer,
            "playlist",
            "id",
            ".ext",
            [["artist", "A"]],
        )

    def testRawFileAnalyzer(self):
        import datetime

        from klangbecken.playlist import FileAddition, MetadataChange, raw_file_analyzer

        # Missing file
        self.assertRaises(
            UnprocessableEntity, raw_file_analyzer, "music", "fileId", "mp3", None
        )

        # Invalid file
        self.assertRaises(
            UnprocessableEntity, raw_file_analyzer, "music", "fileId", "xml", "file"
        )

        # Correct file
        result = raw_file_analyzer("jingles", "fileId", "mp3", "xyz.temp")

        self.assertEqual(result[0], FileAddition("xyz.temp"))
        self.assertTrue(MetadataChange("playlist", "jingles") in result)
        self.assertTrue(MetadataChange("id", "fileId") in result)
        self.assertTrue(MetadataChange("ext", "mp3") in result)
        import_timestamp = [
            ch
            for ch in result
            if (isinstance(ch, MetadataChange) and ch.key == "import_timestamp")
        ][0].value
        two_seconds_ago = datetime.datetime.now() - datetime.timedelta(seconds=2)
        two_seconds_ago = two_seconds_ago.isoformat()
        self.assertGreater(import_timestamp, two_seconds_ago)
        self.assertTrue(MetadataChange("weight", 1) in result)

    def testMutagenTagAnalyzer(self):
        from klangbecken.playlist import MetadataChange as Change, mutagen_tag_analyzer

        # Test regular files
        for ext in ["mp3"]:
            path = os.path.join(self.current_path, "audio", "silence." + ext)
            changes = mutagen_tag_analyzer("music", "fileId", ext, path)
            self.assertEqual(len(changes), 2)
            self.assertIn(Change("artist", "Silence Artist"), changes)
            self.assertIn(Change("title", "Silence Track"), changes)

        # Test regular files with unicode tags
        for suffix in ["-jointstereo.mp3", "-stereo.mp3"]:
            extra, ext = suffix.split(".")
            name = "silence-unicode" + extra + "." + ext
            path = os.path.join(self.current_path, "audio", name)
            changes = mutagen_tag_analyzer("music", "fileId", ext, path)
            self.assertEqual(len(changes), 2)
            self.assertIn(Change("artist", "ÀÉÈ"), changes)
            self.assertIn(Change("title", "ÄÖÜ"), changes)

        # Test MP3 without any tags
        path = os.path.join(self.current_path, "audio", "silence-stripped.mp3")
        changes = mutagen_tag_analyzer("music", "fileId", "mp3", path)
        self.assertEqual(len(changes), 2)
        self.assertIn(Change("artist", ""), changes)
        self.assertIn(Change("title", ""), changes)

        # Test invalid files
        with self.assertRaises(UnprocessableEntity):
            mutagen_tag_analyzer("music", "fileId", "mp3", self.invalid_file)

    def _analyzeOneFile(self, prefix, postfix, gain, cue_in, cue_out):
        from klangbecken.playlist import MetadataChange, ffmpeg_audio_analyzer

        name = prefix + postfix.split(".")[0]
        ext = postfix.split(".")[1]

        path = os.path.join(self.current_path, "audio", name + "." + ext)
        changes = ffmpeg_audio_analyzer("music", name, ext, path)
        self.assertEqual(len(changes), 6)
        for change in changes:
            self.assertIsInstance(change, MetadataChange)
        changes = {key: val for key, val in changes}
        self.assertEqual(
            set(changes.keys()),
            set("channels samplerate bitrate track_gain cue_in cue_out".split()),
        )

        # Track gain negativ and with units
        measured_gain = changes["track_gain"]
        self.assertTrue(measured_gain.endswith(" dB"))

        # Be within ±0.5 dB of expected gain value
        self.assertLess(abs(float(measured_gain[:-3]) - gain), 0.5)

        # Be within the expected values for cue points
        # Don't fade in late, or fade out early!
        self.assertGreater(float(changes["cue_in"]), cue_in - 0.1)
        self.assertLess(float(changes["cue_in"]), cue_in + 0.01)
        self.assertGreater(float(changes["cue_out"]), cue_out - 0.02)
        self.assertLess(float(changes["cue_out"]), cue_out + 0.1)

    def testFFmpegAudioAnalyzer(self):
        from klangbecken.playlist import ffmpeg_audio_analyzer

        test_data = [
            {"prefix": "padded", "gain": -17, "cue_in": 0.2, "cue_out": 0.8},
            {"prefix": "padded-start", "gain": -3.33, "cue_in": 1, "cue_out": 2},
            {"prefix": "padded-end", "gain": -3.55, "cue_in": 0, "cue_out": 1},
            {"prefix": "sine-unicode", "gain": -14, "cue_in": 0, "cue_out": 5},
            {"prefix": "interleaved", "gain": -14.16, "cue_in": 0.2, "cue_out": 0.8},
            {"prefix": "unpadded-interleaved", "gain": -14, "cue_in": 0, "cue_out": 10},
        ]

        for data in test_data:
            for ext in "-jointstereo.mp3 -stereo.mp3".split():
                self._analyzeOneFile(postfix=ext, **data)

        # silence only file
        with self.assertRaises(UnprocessableEntity) as cm:
            path = os.path.join(
                self.current_path, "audio", "silence-unicode-stereo.mp3"
            )
            ffmpeg_audio_analyzer("music", "id1", "mp3", path)
        self.assertIn("track only contains silence", cm.exception.description.lower())

        # invalid file
        with self.assertRaises(UnprocessableEntity):
            ffmpeg_audio_analyzer("music", "id1", "mp3", self.invalid_file)

    def testFFmpegAudioAnalyzerAudioQuality(self):
        from klangbecken.playlist import ffmpeg_audio_analyzer

        with self.assertRaises(UnprocessableEntity) as cm:
            path = os.path.join(self.current_path, "audio", "not-an-audio-file.mp3")
            ffmpeg_audio_analyzer("music", "id1", "mp3", path)
        self.assertIn("cannot process audio data", cm.exception.description.lower())

        with self.assertRaises(UnprocessableEntity) as cm:
            path = os.path.join(self.current_path, "audio", "silence.wav")
            ffmpeg_audio_analyzer("music", "id1", "mp3", path)
        self.assertIn(
            "the track is not a valid mp3 file", cm.exception.description.lower()
        )
        self.assertIn("ulaw", cm.exception.description.lower())

        with self.assertRaises(UnprocessableEntity) as cm:
            path = os.path.join(self.current_path, "audio", "silence.ogg")
            ffmpeg_audio_analyzer("music", "id1", "mp3", path)
        self.assertIn(
            "the track is not a valid mp3 file", cm.exception.description.lower()
        )
        self.assertIn("vorbis", cm.exception.description.lower())

        with self.assertRaises(UnprocessableEntity) as cm:
            path = os.path.join(self.current_path, "audio", "silence-32kHz.mp3")
            ffmpeg_audio_analyzer("music", "id1", "mp3", path)
        self.assertIn("invalid sample rate: 32", cm.exception.description.lower())

        with self.assertRaises(UnprocessableEntity) as cm:
            path = os.path.join(self.current_path, "audio", "sine-unicode-mono.mp3")
            ffmpeg_audio_analyzer("music", "id1", "mp3", path)
        self.assertIn("stereo", cm.exception.description.lower())

        path = os.path.join(self.current_path, "audio", "sine-unicode-mono.mp3")
        changes = ffmpeg_audio_analyzer("jingles", "id1", "mp3", path)
        self.assertEqual(len(changes), 6)

        with self.assertRaises(UnprocessableEntity) as cm:
            path = os.path.join(self.current_path, "audio", "silence-112kbps.mp3")
            ffmpeg_audio_analyzer("music", "id1", "mp3", path)
        self.assertIn("bitrate too low: 112 < 128", cm.exception.description.lower())


class ProcessorsTestCase(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        os.mkdir(os.path.join(self.tempdir, "music"))

        current_path = os.path.dirname(os.path.realpath(__file__))
        for ext in ".mp3 -stripped.mp3".split():
            shutil.copyfile(
                os.path.join(current_path, "audio", "silence" + ext),
                os.path.join(self.tempdir, "music", "silence" + ext),
            )

        with open(os.path.join(self.tempdir, "index.json"), "w") as f:
            print("{}", file=f)
        open(os.path.join(self.tempdir, "music.m3u"), "w").close()
        open(os.path.join(self.tempdir, "jingles.m3u"), "w").close()

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def testCheckProcessor(self):
        from klangbecken.playlist import MetadataChange, check_processor

        # Invalid key
        with self.assertRaises(UnprocessableEntity) as cm:
            check_processor(
                self.tempdir,
                "playlist",
                "id",
                "ext",
                [MetadataChange("invalid", "xyz")],
            )
        self.assertTrue("Invalid metadata key" in cm.exception.description)

        # Wrong data type (str instead of int)
        with self.assertRaises(UnprocessableEntity) as cm:
            check_processor(
                self.tempdir, "playlist", "id", "ext", [MetadataChange("weight", "1")]
            )
        self.assertTrue("Invalid data format" in cm.exception.description)

        # Wrong data format (uuid)
        with self.assertRaises(UnprocessableEntity) as cm:
            check_processor(
                self.tempdir, "playlist", "id", "ext", [MetadataChange("id", "xyz")]
            )
        self.assertTrue("Invalid data format" in cm.exception.description)
        self.assertTrue("Regex" in cm.exception.description)

        # Wrong data format (negative weight)
        with self.assertRaises(UnprocessableEntity) as cm:
            check_processor(
                self.tempdir, "playlist", "id", "ext", [MetadataChange("weight", -5)]
            )
        self.assertTrue("Invalid data format" in cm.exception.description)

        # Invalid action class
        with self.assertRaises(ValueError) as cm:
            check_processor(self.tempdir, "playlist", "id", "ext", ["whatever"])

    def testFilterDuplicatesProcessor(self):
        from klangbecken.playlist import (
            FileAddition,
            MetadataChange,
            filter_duplicates_processor,
            index_processor,
        )

        file_ = FileStorage(io.BytesIO(b"abc"), "filename.mp3")
        changes = [
            FileAddition(file_),
            MetadataChange("original_filename", "filename.mp3"),
            MetadataChange("artist", "Artist"),
            MetadataChange("title", "Title"),
            MetadataChange("playlist", "music"),
        ]
        filter_duplicates_processor(self.tempdir, "music", "id1", ".mp3", changes)

        index_processor(self.tempdir, "music", "id1", ".mp3", changes)
        with self.assertRaises(UnprocessableEntity) as cm:
            filter_duplicates_processor(self.tempdir, "music", "id", "mp3", changes)
        self.assertTrue("Duplicate file entry" in cm.exception.description)

    def testRawFileProcessor(self):
        from klangbecken.playlist import (
            FileAddition,
            FileDeletion,
            MetadataChange,
            raw_file_processor,
        )

        filename = os.path.join(self.tempdir, "music", "silence.mp3")
        addition = FileAddition(filename)
        change = MetadataChange("key", "value")
        delete = FileDeletion()

        # File addition
        raw_file_processor(self.tempdir, "music", "id1", "mp3", [addition])
        path = os.path.join(self.tempdir, "music", "id1.mp3")
        self.assertTrue(os.path.isfile(path))

        # File change (nothing happens) and deletion
        raw_file_processor(self.tempdir, "music", "id1", "mp3", [change])
        raw_file_processor(self.tempdir, "music", "id1", "mp3", [delete])
        self.assertTrue(not os.path.isfile(path))

        # Invalid change (not found)
        self.assertRaises(
            NotFound, raw_file_processor, self.tempdir, "music", "id1", "mp3", [change]
        )

        # Invalid deletion (not found)
        self.assertRaises(
            NotFound, raw_file_processor, self.tempdir, "music", "id1", "mp3", [delete]
        )

    def testIndexProcessor(self):
        from klangbecken.playlist import (
            FileAddition,
            FileDeletion,
            MetadataChange,
            index_processor,
        )

        index_path = os.path.join(self.tempdir, "index.json")

        # Add two new files
        index_processor(
            self.tempdir, "music", "fileId1", "mp3", [FileAddition("filename.txt")]
        )
        index_processor(
            self.tempdir, "music", "fileId2", "mp3", [FileAddition("filename.txt")]
        )

        with open(index_path) as f:
            data = json.load(f)

        self.assertTrue("fileId1" in data)
        self.assertTrue("fileId2" in data)

        # Set some initial metadata
        index_processor(
            self.tempdir, "music", "fileId1", "mp3", [MetadataChange("key1", "value1")]
        )
        index_processor(
            self.tempdir,
            "music",
            "fileId2",
            ".mp3",
            [MetadataChange("key1", "value1"), MetadataChange("key2", "value2")],
        )

        with open(index_path) as f:
            data = json.load(f)

        self.assertTrue("key1" in data["fileId1"])
        self.assertEqual(data["fileId1"]["key1"], "value1")
        self.assertTrue("key1" in data["fileId2"])
        self.assertEqual(data["fileId2"]["key1"], "value1")
        self.assertTrue("key2" in data["fileId2"])
        self.assertEqual(data["fileId2"]["key2"], "value2")

        # Modify metadata
        index_processor(
            self.tempdir,
            "music",
            "fileId1",
            "mp3",
            [MetadataChange("key1", "value1-1"), MetadataChange("key2", "value2-1")],
        )
        index_processor(
            self.tempdir,
            "music",
            "fileId2",
            "mp3",
            [MetadataChange("key2", "value2-1-œ")],
        )

        with open(index_path) as f:
            data = json.load(f)

        self.assertTrue("key1" in data["fileId1"])
        self.assertEqual(data["fileId1"]["key1"], "value1-1")
        self.assertTrue("key2" in data["fileId1"])
        self.assertEqual(data["fileId1"]["key2"], "value2-1")
        self.assertTrue("key1" in data["fileId2"])
        self.assertEqual(data["fileId2"]["key1"], "value1")
        self.assertTrue("key2" in data["fileId2"])
        self.assertEqual(data["fileId2"]["key2"], "value2-1-œ")

        # Delete one file
        index_processor(self.tempdir, "music", "fileId1", ".mp3", [FileDeletion()])

        with open(index_path) as f:
            data = json.load(f)

        self.assertTrue("fileId1" not in data)
        self.assertTrue("fileId2" in data)

        # Try duplicating file ids
        with self.assertRaisesRegex(UnprocessableEntity, "Duplicate"):
            index_processor(
                self.tempdir, "music", "fileId2", ".mp3", [FileAddition("filename.txt")]
            )
        with self.assertRaisesRegex(UnprocessableEntity, "Duplicate"):
            index_processor(
                self.tempdir,
                "jingles",
                "fileId2",
                ".mp3",
                [FileAddition("filename.txt")],
            )
        with self.assertRaisesRegex(UnprocessableEntity, "Duplicate"):
            index_processor(
                self.tempdir, "music", "fileId2", ".mp3", [FileAddition("filename.txt")]
            )

        # Try modifying non existent files
        with self.assertRaises(NotFound):
            index_processor(
                self.tempdir,
                "music",
                "fileIdXY",
                "mp3",
                [MetadataChange("key", "val")],
            )

        # Try deleting non existent file ids
        with self.assertRaises(NotFound):
            index_processor(self.tempdir, "music", "fileIdXY", "mp3", [FileDeletion()])

        with open(index_path) as f:
            data = json.load(f)
        self.assertTrue("fileId2" in data)
        self.assertTrue("fileXY" not in data)

    def testFileTagProcessor(self):
        from mutagen import File

        from klangbecken.playlist import (
            FileAddition,
            FileDeletion,
            MetadataChange,
            file_tag_processor,
        )

        # No-ops
        file_tag_processor(
            self.tempdir,
            "nonexistant",
            "fileIdZZ",
            "mp3",
            [
                FileAddition(""),
                MetadataChange("id", "abc"),
                MetadataChange("playlist", "abc"),
                MetadataChange("ext", "abc"),
                MetadataChange("nonexistant", "abc"),
                FileDeletion(),
            ],
        )

        changes = {
            "artist": "New Artist (๛)",
            "title": "New Title (᛭)",
            "cue_in": "0.123",
            "cue_out": "123",
            "track_gain": "-12 dB",
        }
        metadata_changes = [MetadataChange(key, val) for key, val in changes.items()]

        # Valid files
        for filename in ["silence.mp3", "silence-stripped.mp3"]:
            prefix, ext = filename.split(".")

            path = os.path.join(self.tempdir, "music", filename)
            mutagenfile = File(path, easy=True)

            # Make sure tags are not already the same before updating
            for key, val in changes.items():
                self.assertNotEqual(val, mutagenfile.get(key, [""])[0])

            # Update and verify tags
            file_tag_processor(self.tempdir, "music", prefix, ext, metadata_changes)
            mutagenfile = File(path, easy=True)
            for key, val in changes.items():
                self.assertEqual(len(mutagenfile.get(key, [""])), 1)
                self.assertEqual(val, mutagenfile.get(key, [""])[0])

    def testPlaylistProcessor(self):
        from klangbecken.playlist import (
            FileDeletion,
            MetadataChange,
            playlist_processor,
        )

        music_path = os.path.join(self.tempdir, "music.m3u")
        jingles_path = os.path.join(self.tempdir, "jingles.m3u")

        # Update playlist weight (initial)
        playlist_processor(
            self.tempdir, "music", "fileId1", "mp3", [MetadataChange("weight", 2)]
        )

        with open(music_path) as f:
            lines = f.read().split("\n")
        entries = [ln for ln in lines if ln.endswith("music/fileId1.mp3")]
        self.assertEqual(len(entries), 2)

        with open(jingles_path) as f:
            data = f.read()
        self.assertEqual(data, "")

        # Update playlist weight
        playlist_processor(
            self.tempdir, "music", "fileId1", "mp3", [MetadataChange("weight", 4)]
        )

        with open(music_path) as f:
            lines = f.read().split("\n")
        entries = [ln for ln in lines if ln.endswith("music/fileId1.mp3")]
        self.assertEqual(len(entries), 4)

        with open(jingles_path) as f:
            data = f.read()
        self.assertEqual(data, "")

        # Set playlist weight to zero (same as delete)
        playlist_processor(
            self.tempdir, "music", "fileId1", "mp3", [MetadataChange("weight", 0)]
        )

        with open(music_path) as f:
            data = f.read()
        self.assertEqual(data, "")

        with open(jingles_path) as f:
            data = f.read()
        self.assertEqual(data, "")

        # Add more files to playlist
        playlist_processor(
            self.tempdir, "music", "fileId1", "mp3", [MetadataChange("weight", 2)]
        )
        playlist_processor(
            self.tempdir, "music", "fileId2", "mp3", [MetadataChange("weight", 1)]
        )
        playlist_processor(
            self.tempdir, "music", "fileId3", "mp3", [MetadataChange("weight", 3)]
        )
        playlist_processor(
            self.tempdir, "jingles", "fileId4", "mp3", [MetadataChange("weight", 2)]
        )
        playlist_processor(
            self.tempdir, "jingles", "fileId5", "mp3", [MetadataChange("weight", 3)]
        )

        with open(music_path) as f:
            lines = [ln.strip() for ln in f.readlines()]
        entries = [ln for ln in lines if ln.endswith("music/fileId1.mp3")]
        self.assertEqual(len(entries), 2)
        entries = [ln for ln in lines if ln.endswith("music/fileId2.mp3")]
        self.assertEqual(len(entries), 1)
        entries = [ln for ln in lines if ln.endswith("music/fileId3.mp3")]
        self.assertEqual(len(entries), 3)

        with open(jingles_path) as f:
            lines = [ln.strip() for ln in f.readlines()]
        entries = [ln for ln in lines if ln.endswith("jingles/fileId4.mp3")]
        self.assertEqual(len(entries), 2)
        entries = [ln for ln in lines if ln.endswith("jingles/fileId5.mp3")]
        self.assertEqual(len(entries), 3)

        # Delete non existing file (must be possible)
        playlist_processor(self.tempdir, "music", "fileIdXY", "mp3", [FileDeletion()])
        with open(music_path) as f:
            lines = [ln.strip() for ln in f.readlines()]
        self.assertEqual(len(lines), 6)
        self.assertTrue(all(lines))

        with open(jingles_path) as f:
            lines = [ln.strip() for ln in f.readlines()]
        self.assertEqual(len(lines), 5)
        self.assertTrue(all(lines))

        # Delete existing file
        playlist_processor(self.tempdir, "music", "fileId1", "mp3", [FileDeletion()])
        with open(music_path) as f:
            lines = [ln.strip() for ln in f.readlines()]
        self.assertEqual(len(lines), 4)
        self.assertTrue(all(lines))
        entries = [ln for ln in lines if ln.endswith("music/fileId1.mp3")]
        self.assertListEqual(entries, [])

        with open(jingles_path) as f:
            lines = [ln.strip() for ln in f.readlines()]
        self.assertEqual(len(lines), 5)
        self.assertTrue(all(lines))

        # Multiple deletes
        playlist_processor(self.tempdir, "music", "fileId3", "mp3", [FileDeletion()])
        playlist_processor(self.tempdir, "jingles", "fileId4", "mp3", [FileDeletion()])
        playlist_processor(self.tempdir, "jingles", "fileId5", "mp3", [FileDeletion()])

        with open(music_path) as f:
            lines = [ln.strip() for ln in f.readlines()]
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].endswith("music/fileId2.mp3"))

        with open(jingles_path) as f:
            data = f.read()
        self.assertEqual(data, "")
