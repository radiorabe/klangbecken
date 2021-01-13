import io
import json
import os
import shutil
import tempfile
import unittest
import uuid
from unittest import mock

from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import NotFound, UnprocessableEntity
from werkzeug.test import Client
from werkzeug.wrappers import BaseResponse


class WSGIAppTest(unittest.TestCase):
    def test_application(self):
        from klangbecken.api import klangbecken_api

        application = klangbecken_api("inexistent_dir", "secret", "player.sock")
        self.assertTrue(callable(application))


class APITestCase(unittest.TestCase):
    @mock.patch("klangbecken.api.ExternalAuth", lambda app, *args, **kwargs: app)
    def setUp(self):
        from klangbecken.api import klangbecken_api
        from klangbecken.playlist import FileAddition, MetadataChange

        self.upload_analyzer = mock.Mock(
            return_value=[
                FileAddition("testfile"),
                MetadataChange("testkey", "testvalue"),
            ]
        )
        self.update_analyzer = mock.Mock(return_value=["UpdateChange"])
        self.processor = mock.MagicMock()

        with mock.patch(
            "klangbecken.api.DEFAULT_UPLOAD_ANALYZERS", [self.upload_analyzer]
        ), mock.patch(
            "klangbecken.api.DEFAULT_UPDATE_ANALYZERS", [self.update_analyzer]
        ), mock.patch(
            "klangbecken.api.DEFAULT_PROCESSORS", [self.processor]
        ):
            app = klangbecken_api(
                "secret",
                "data_dir",
                "player.sock",
            )
        self.client = Client(app, BaseResponse)

    def testUrls(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        resp = self.client.get("/playlist/music/")
        self.assertEqual(resp.status_code, 405)
        resp = self.client.get("/playlist/jingles/")
        self.assertEqual(resp.status_code, 405)
        resp = self.client.get("/playlist/nonexistant/")
        self.assertEqual(resp.status_code, 404)
        resp = self.client.get("/öäü/")
        self.assertEqual(resp.status_code, 404)
        resp = self.client.post("/playlist/jingles")
        self.assertIn(resp.status_code, (301, 308))
        resp = self.client.post("/playlist/music/")
        self.assertEqual(resp.status_code, 422)
        resp = self.client.post("/playlist/jingles/something")
        self.assertEqual(resp.status_code, 404)
        resp = self.client.put("/playlist/music/")
        self.assertEqual(resp.status_code, 405)
        resp = self.client.put("/playlist/jingles/something")
        self.assertEqual(resp.status_code, 404)
        resp = self.client.put("/playlist/jingles/something.mp3")
        self.assertEqual(resp.status_code, 404)
        resp = self.client.put("/playlist/music/" + str(uuid.uuid4()))
        self.assertEqual(resp.status_code, 404)
        resp = self.client.put("/playlist/music/" + str(uuid.uuid4()) + ".mp3")
        self.assertEqual(resp.status_code, 415)
        resp = self.client.put("/playlist/jingles/" + str(uuid.uuid4()) + ".ogg")
        self.assertEqual(resp.status_code, 415)
        resp = self.client.put("/playlist/music/" + str(uuid.uuid4()) + ".flac")
        self.assertEqual(resp.status_code, 415)
        resp = self.client.put("/playlist/jingles/" + str(uuid.uuid4()) + ".ttt")
        self.assertEqual(resp.status_code, 404)
        resp = self.client.delete("/playlist/music/")
        self.assertEqual(resp.status_code, 405)
        resp = self.client.delete("/playlist/jingles/something")
        self.assertEqual(resp.status_code, 404)
        resp = self.client.delete("/playlist/jingles/something.mp3")
        self.assertEqual(resp.status_code, 404)
        resp = self.client.delete("/playlist/music/" + str(uuid.uuid4()))
        self.assertEqual(resp.status_code, 404)
        resp = self.client.delete("/playlist/jingles/" + str(uuid.uuid4()) + ".mp3")
        self.assertEqual(resp.status_code, 200)
        resp = self.client.delete("/playlist/music/" + str(uuid.uuid4()) + ".ogg")
        self.assertEqual(resp.status_code, 200)
        resp = self.client.delete("/playlist/jingles/" + str(uuid.uuid4()) + ".flac")
        self.assertEqual(resp.status_code, 200)
        resp = self.client.delete("/playlist/music/" + str(uuid.uuid4()) + ".ttt")
        self.assertEqual(resp.status_code, 404)

    def testPlayerInfo(self):
        resp = self.client.get("/player/")
        self.assertEqual(resp.status_code, 404)
        self.assertIn(b"Player not running", resp.data)

    def testUpload(self):
        from klangbecken.playlist import FileAddition, MetadataChange

        # Correct upload
        resp = self.client.post(
            "/playlist/music/", data={"file": (io.BytesIO(b"testcontent"), "test.mp3")}
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        fileId = list(data.keys())[0]
        self.assertEqual(fileId, str(uuid.UUID(fileId)))
        self.assertEqual(list(data.values())[0], {"testkey": "testvalue"})
        self.update_analyzer.assert_not_called()
        self.upload_analyzer.assert_called_once()
        args = self.upload_analyzer.call_args[0]
        self.assertEqual(args[0], "music")
        self.assertEqual(args[1], fileId)
        self.assertEqual(args[2], "mp3")
        self.assertTrue(isinstance(args[3], FileStorage))
        self.assertEqual(args[3].filename, "test.mp3")
        self.assertEqual(args[3].mimetype, "audio/mpeg")
        self.assertTrue(args[3].closed)

        self.processor.assert_called_once_with(
            "data_dir",
            "music",
            fileId,
            "mp3",
            [FileAddition("testfile"), MetadataChange("testkey", "testvalue")],
        )

        self.upload_analyzer.reset_mock()
        self.processor.reset_mock()

        # Wrong attribute name
        resp = self.client.post(
            "/playlist/music/",
            data={"not-file": (io.BytesIO(b"testcontent"), "test.mp3")},
        )
        self.assertEqual(resp.status_code, 422)
        self.assertIn(b"No file attribute named", resp.data)
        self.update_analyzer.assert_not_called()
        self.upload_analyzer.assert_not_called()
        self.processor.assert_not_called()

        # File as normal text attribute
        resp = self.client.post(
            "/playlist/music/", data={"file": "testcontent", "filename": "test.mp3"}
        )
        self.assertEqual(resp.status_code, 422)
        self.assertIn(b"No file attribute named", resp.data)
        self.update_analyzer.assert_not_called()
        self.upload_analyzer.assert_not_called()
        self.processor.assert_not_called()

    def testUpdate(self):
        # Update weight correctly
        fileId = str(uuid.uuid4())
        resp = self.client.put(
            "/playlist/music/" + fileId + ".mp3",
            data=json.dumps({"weight": 4}),
            content_type="text/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.update_analyzer.assert_called_once_with(
            "music", fileId, "mp3", {"weight": 4}
        )
        self.upload_analyzer.assert_not_called()
        self.processor.assert_called_once_with(
            "data_dir", "music", fileId, "mp3", ["UpdateChange"]
        )
        self.update_analyzer.reset_mock()
        self.processor.reset_mock()

        # Update artist and title correctly
        resp = self.client.put(
            "/playlist/music/" + fileId + ".mp3",
            data=json.dumps({"artist": "A", "title": "B"}),
            content_type="text/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.update_analyzer.assert_called_once_with(
            "music", fileId, "mp3", {"artist": "A", "title": "B"}
        )
        self.processor.assert_called_once_with(
            "data_dir", "music", fileId, "mp3", ["UpdateChange"]
        )
        self.update_analyzer.reset_mock()
        self.processor.reset_mock()

        # Update with invalid json format
        resp = self.client.put(
            "/playlist/music/" + fileId + ".mp3",
            data='{ a: " }',
            content_type="text/json",
        )
        self.assertEqual(resp.status_code, 415)
        self.assertIn(b"invalid JSON", resp.data)
        self.update_analyzer.assert_not_called()

        # Update with invalid unicode format
        resp = self.client.put(
            "/playlist/music/" + fileId + ".mp3", data=b"\xFF", content_type="text/json"
        )
        self.assertEqual(resp.status_code, 415)
        self.assertIn(b"invalid UTF-8 data", resp.data)
        self.update_analyzer.assert_not_called()

    def testDelete(self):
        from klangbecken.playlist import FileDeletion

        fileId = str(uuid.uuid4())
        resp = self.client.delete("/playlist/music/" + fileId + ".mp3")
        self.assertEqual(resp.status_code, 200)
        self.update_analyzer.assert_not_called()
        self.upload_analyzer.assert_not_called()
        self.processor.assert_called_once_with(
            "data_dir", "music", fileId, "mp3", [FileDeletion()]
        )
        self.upload_analyzer.reset_mock()
        self.processor.reset_mock()


class AuthTestCase(unittest.TestCase):
    def setUp(self):
        from klangbecken.api import klangbecken_api

        with mock.patch(
            "klangbecken.api.DEFAULT_UPLOAD_ANALYZERS", [lambda *args: []]
        ), mock.patch(
            "klangbecken.api.DEFAULT_UPDATE_ANALYZERS", [lambda *args: []]
        ), mock.patch(
            "klangbecken.api.DEFAULT_PROCESSORS", [lambda *args: None]
        ):
            app = klangbecken_api(
                "inexistent_dir",
                "secret",
                "nix.sock",
            )
        self.client = Client(app, BaseResponse)

    def testFailingAuth(self):
        resp = self.client.post("/playlist/music/")
        self.assertEqual(resp.status_code, 401)
        resp = self.client.put("/playlist/jingles/" + str(uuid.uuid4()) + ".mp3")
        self.assertEqual(resp.status_code, 401)
        resp = self.client.delete("/playlist/music/" + str(uuid.uuid4()) + ".ogg")
        self.assertEqual(resp.status_code, 401)

    def testFailingLogin(self):
        resp = self.client.get("/auth/login/")
        self.assertEqual(resp.status_code, 401)
        self.assertNotIn("Set-Cookie", resp.headers)

        resp = self.client.post("/auth/login/")
        self.assertEqual(resp.status_code, 401)
        self.assertNotIn("Set-Cookie", resp.headers)

    def testLogin(self):
        resp = self.client.post("/auth/login/", environ_base={"REMOTE_USER": "xyz"})
        self.assertEqual(resp.status_code, 200)
        response_data = json.loads(resp.data)
        self.assertIn("token", response_data)
        self.assertRegex(response_data["token"], r"([a-zA-Z0-9_-]+\.){2}[a-zA-Z0-9_-]+")


class PlayerAPITestCase(unittest.TestCase):
    def setUp(self):
        from klangbecken.api import player_api

        self.liquidsoap_client = mock.MagicMock()
        self.liquidsoap_client.info = mock.Mock(return_value="info")
        self.tempdir = tempfile.mkdtemp()
        app = player_api(self.liquidsoap_client, self.tempdir)
        os.mkdir(os.path.join(self.tempdir, "music"))
        with open(os.path.join(self.tempdir, "music", "titi.mp3"), "w"):
            pass
        self.client = Client(app, BaseResponse)

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def testInfo(self):
        self.liquidsoap_client.info = mock.Mock(return_value="info")
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"info", resp.data)
        self.liquidsoap_client.info.assert_called_once_with()

    def testQueueListCorrect(self):
        self.liquidsoap_client.queue = mock.Mock(return_value="queue")
        resp = self.client.get("/queue/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"queue", resp.data)
        self.liquidsoap_client.queue.assert_called_once_with()

    def testQueuePushCorrect(self):
        self.liquidsoap_client.push = mock.Mock(return_value="my_id")
        resp = self.client.post(
            "/queue/", data=json.dumps({"filename": "music/titi.mp3"})
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data["queue_id"], "my_id")
        self.liquidsoap_client.push.assert_called_once_with(
            os.path.join(self.tempdir, "music", "titi.mp3")
        )

    def testQueuePushIncorrect(self):
        self.liquidsoap_client.push = mock.Mock(return_value="my_track_id")
        resp = self.client.post(
            "/queue/", data=json.dumps({"filename": "music/tata.mp3"})
        )
        self.assertEqual(resp.status_code, 404)
        self.liquidsoap_client.push.assert_not_called()

        resp = self.client.post(
            "/queue/", data=json.dumps({"filename": "music/titi.abc"})
        )
        self.assertEqual(resp.status_code, 422)
        self.liquidsoap_client.push.assert_not_called()

        resp = self.client.post("/queue/", data=json.dumps({"file": "music/titi.mp3"}))
        self.assertEqual(resp.status_code, 422)
        self.liquidsoap_client.push.assert_not_called()

    def testQueueDelete(self):
        resp = self.client.delete("/queue/15")
        self.assertEqual(resp.status_code, 200)
        self.liquidsoap_client.delete.assert_called_once_with("15")


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
        fileStorage = FileStorage(filename="filename-äöü")
        result = raw_file_analyzer("jingles", "fileId", "ogg", fileStorage)

        # Assure file is reset correctly
        self.assertEqual(fileStorage.tell(), 0)
        self.assertFalse(fileStorage.closed)

        self.assertEqual(result[0], FileAddition(fileStorage))
        self.assertTrue(MetadataChange("playlist", "jingles") in result)
        self.assertTrue(MetadataChange("id", "fileId") in result)
        self.assertTrue(MetadataChange("ext", "ogg") in result)
        self.assertTrue(MetadataChange("original_filename", "filename-äöü") in result)
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
        for ext in ["mp3", "ogg", "flac"]:
            path = os.path.join(self.current_path, "audio", "silence." + ext)
            with open(path, "rb") as f:
                fs = FileStorage(f)
                changes = mutagen_tag_analyzer("music", "fileId", ext, fs)
                self.assertEqual(len(changes), 4)
                self.assertIn(Change("artist", "Silence Artist"), changes)
                self.assertIn(Change("title", "Silence Track"), changes)
                self.assertIn(Change("album", "Silence Album"), changes)
                self.assertIn(Change("length", 1.0), changes)

                # Assure file is reset correctly
                self.assertEqual(f.tell(), 0)
                self.assertFalse(f.closed)

        # Test regular files with unicode tags
        for suffix in ["-jointstereo.mp3", "-stereo.mp3", ".ogg", ".flac"]:
            extra, ext = suffix.split(".")
            name = "silence-unicode" + extra + "." + ext
            path = os.path.join(self.current_path, "audio", name)
            with open(path, "rb") as f:
                fs = FileStorage(f)
                changes = mutagen_tag_analyzer("music", "fileId", ext, fs)
                self.assertEqual(len(changes), 4)
                self.assertIn(Change("artist", "ÀÉÈ"), changes)
                self.assertIn(Change("title", "ÄÖÜ"), changes)
                self.assertIn(Change("album", "☀⚛♬"), changes)
                self.assertIn(Change("length", 1.0), changes)

        # Test MP3 without any tags
        path = os.path.join(self.current_path, "audio", "silence-stripped.mp3")
        with open(path, "rb") as f:
            fs = FileStorage(f)
            changes = mutagen_tag_analyzer("music", "fileId", "mp3", fs)
            self.assertEqual(len(changes), 4)
            self.assertIn(Change("artist", ""), changes)
            self.assertIn(Change("title", ""), changes)
            self.assertIn(Change("album", ""), changes)
            self.assertIn(Change("length", 1.0), changes)

        # Test invalid files
        for ext in ["mp3", "ogg", "flac"]:
            path = os.path.join(self.current_path, "audio", "silence." + ext)
            fs = FileStorage(io.BytesIO(b"\0" * 1024))
            with self.assertRaises(UnprocessableEntity):
                mutagen_tag_analyzer("music", "fileId", ext, fs)

    def _analyzeOneFile(self, prefix, postfix, gain, cue_in, cue_out):
        from klangbecken.playlist import MetadataChange, ffmpeg_audio_analyzer

        name = prefix + postfix.split(".")[0]
        ext = postfix.split(".")[1]

        path = os.path.join(self.current_path, "audio", name + "." + ext)
        with open(path, "rb") as f:
            fs = FileStorage(f)

            changes = ffmpeg_audio_analyzer("music", name, ext, fs)
            self.assertEqual(len(changes), 3)
            for change in changes:
                self.assertIsInstance(change, MetadataChange)
            changes = {key: val for key, val in changes}
            self.assertEqual(
                set(changes.keys()), set("track_gain cue_in cue_out".split())
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

            # Assure file is reset correctly
            self.assertEqual(f.tell(), 0)
            self.assertFalse(f.closed)

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
            for ext in "-jointstereo.mp3 -stereo.mp3 .ogg .flac".split():
                self._analyzeOneFile(postfix=ext, **data)

        # silence only file
        with self.assertRaises(UnprocessableEntity) as cm:
            path = os.path.join(self.current_path, "audio", "silence-unicode.flac")
            with open(path, "rb") as f:
                fs = FileStorage(f)
                ffmpeg_audio_analyzer("music", "id1", "mp3", fs)
        self.assertIn("track only contains silence", cm.exception.description.lower())

        # too long silence intro file
        with self.assertRaises(UnprocessableEntity) as cm:
            path = os.path.join(self.current_path, "audio", "padded-start-long.flac")
            with open(path, "rb") as f:
                fs = FileStorage(f)
                ffmpeg_audio_analyzer("music", "id1", "mp3", fs)
        self.assertIn("too much silence", cm.exception.description.lower())

        # invalid file
        with self.assertRaises(UnprocessableEntity):
            with open(self.invalid_file, "rb") as f:
                fs = FileStorage(f)
                ffmpeg_audio_analyzer("music", "id1", "mp3", fs)


class ProcessorsTestCase(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        os.mkdir(os.path.join(self.tempdir, "music"))

        current_path = os.path.dirname(os.path.realpath(__file__))
        for ext in ".mp3 -stripped.mp3 .ogg .flac".split():
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

        # Wrong data format (negative length)
        with self.assertRaises(UnprocessableEntity) as cm:
            check_processor(
                self.tempdir, "playlist", "id", "ext", [MetadataChange("length", -5.0)]
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

        file_ = FileStorage(io.BytesIO(b"abc"), "filename-éàè.txt")
        addition = FileAddition(file_)
        change = MetadataChange("key", "value")
        delete = FileDeletion()

        # File addition
        raw_file_processor(self.tempdir, "music", "id1", "mp3", [addition])
        path = os.path.join(self.tempdir, "music", "id1.mp3")
        self.assertTrue(os.path.isfile(path))
        with open(path) as f:
            self.assertEqual(f.read(), "abc")

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
        file_ = FileStorage(io.BytesIO(b"abc"), "filename.txt")
        index_processor(self.tempdir, "music", "fileId1", "mp3", [FileAddition(file_)])
        index_processor(self.tempdir, "music", "fileId2", "ogg", [FileAddition(file_)])

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
            ".ogg",
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
            "ogg",
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
                self.tempdir, "music", "fileId2", ".ogg", [FileAddition(file_)]
            )
        with self.assertRaisesRegex(UnprocessableEntity, "Duplicate"):
            index_processor(
                self.tempdir, "jingles", "fileId2", ".mp3", [FileAddition(file_)]
            )
        with self.assertRaisesRegex(UnprocessableEntity, "Duplicate"):
            index_processor(
                self.tempdir, "music", "fileId2", ".mp3", [FileAddition(file_)]
            )

        # Try modifying non existent files
        with self.assertRaises(NotFound):
            index_processor(
                self.tempdir,
                "music",
                "fileIdXY",
                "ogg",
                [MetadataChange("key", "val")],
            )

        # Try deleting non existent file ids
        with self.assertRaises(NotFound):
            index_processor(self.tempdir, "music", "fileIdXY", "ogg", [FileDeletion()])

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
                MetadataChange("length", "abc"),
                MetadataChange("nonexistant", "abc"),
                FileDeletion(),
            ],
        )

        changes = {
            "artist": "New Artist (๛)",
            "title": "New Title (᛭)",
            "album": "New Album (٭)",
            "cue_in": "0.123",
            "cue_out": "123",
            "track_gain": "-12 dB",
        }
        metadata_changes = [MetadataChange(key, val) for key, val in changes.items()]

        # Valid files
        for filename in [
            "silence.mp3",
            "silence-stripped.mp3",
            "silence.ogg",
            "silence.flac",
        ]:
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
            self.tempdir, "music", "fileId2", "ogg", [MetadataChange("weight", 1)]
        )
        playlist_processor(
            self.tempdir, "music", "fileId3", "flac", [MetadataChange("weight", 3)]
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
        entries = [ln for ln in lines if ln.endswith("music/fileId2.ogg")]
        self.assertEqual(len(entries), 1)
        entries = [ln for ln in lines if ln.endswith("music/fileId3.flac")]
        self.assertEqual(len(entries), 3)

        with open(jingles_path) as f:
            lines = [ln.strip() for ln in f.readlines()]
        entries = [ln for ln in lines if ln.endswith("jingles/fileId4.mp3")]
        self.assertEqual(len(entries), 2)
        entries = [ln for ln in lines if ln.endswith("jingles/fileId5.mp3")]
        self.assertEqual(len(entries), 3)

        # Delete non existing file (must be possible)
        playlist_processor(self.tempdir, "music", "fileIdXY", "ogg", [FileDeletion()])
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
        playlist_processor(self.tempdir, "music", "fileId3", "flac", [FileDeletion()])
        playlist_processor(self.tempdir, "jingles", "fileId4", "mp3", [FileDeletion()])
        playlist_processor(self.tempdir, "jingles", "fileId5", "mp3", [FileDeletion()])

        with open(music_path) as f:
            lines = [ln.strip() for ln in f.readlines()]
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].endswith("music/fileId2.ogg"))

        with open(jingles_path) as f:
            data = f.read()
        self.assertEqual(data, "")
