import json
import os
import shutil
import sys
import tempfile
import unittest

from .utils import capture


class FsckTestCase(unittest.TestCase):
    def setUp(self):
        from klangbecken import PLAYLISTS
        from klangbecken import _check_data_dir, import_cmd
        self.current_path = os.path.dirname(os.path.realpath(__file__))
        self.tempdir = tempfile.mkdtemp()
        self.music_dir = os.path.join(self.tempdir, 'music')
        self.jingles_dir = os.path.join(self.tempdir, 'jingles')
        _check_data_dir(self.tempdir, create=True)

        # Correctly import a couple of files
        files = [os.path.join(self.current_path, 'audio', 'padded' + ext)
                 for ext in '.ogg .flac -stereo.mp3'.split()]
        for playlist in PLAYLISTS:
            try:
                args = [self.tempdir, playlist, files, True]
                with capture(import_cmd, *args) as (out, err, ret):
                    pass
            except SystemExit as e:
                if e.code != 0:
                    print(err, file=sys.stderr)
                    raise(RuntimeError('Command execution failed'))

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def testFsckCorruptIndexJson(self):
        from klangbecken import main

        index_path = os.path.join(self.tempdir, 'index.json')
        with open(index_path, 'w'):
            pass

        argv, sys.argv = sys.argv, ['', 'fsck', '-d', self.tempdir]
        try:
            with self.assertRaises(SystemExit) as cm:
                with capture(main) as (out, err, ret):
                    self.assertIn('ERROR', err)
            self.assertEqual(cm.exception.code, 1)
        finally:
            sys.arv = argv

    def testFsckCorruptDataDir(self):
        from klangbecken import main

        music_path = os.path.join(self.tempdir, 'music')
        shutil.rmtree(music_path)

        argv, sys.argv = sys.argv, ['', 'fsck', '-d', self.tempdir]
        try:
            with self.assertRaises(SystemExit) as cm:
                with capture(main) as (out, err, ret):
                    self.assertIn('ERROR', err)
            self.assertEqual(cm.exception.code, 1)
        finally:
            sys.arv = argv

    def testFsck(self):
        from klangbecken import main
        argv, sys.argv = sys.argv, ['', 'fsck', '-d', 'invalid']
        try:
            # inexistent data_dir
            with self.assertRaises(SystemExit) as cm:
                with capture(main) as (out, err, ret):
                    self.assertIn('ERROR', err)
                    self.assertIn("Data directory 'invalid' does not exist",
                                  err)
            self.assertEqual(cm.exception.code, 1)

            sys.argv[-1] = self.tempdir

            # correct invocation
            with self.assertRaises(SystemExit) as cm:
                with capture(main) as (out, err, ret):
                    self.assertEqual(err.strip(), '')
            self.assertEqual(cm.exception.code, 0)
        finally:
            sys.arv = argv

    def testIndexWithWrongId(self):
        from klangbecken import main
        argv, sys.argv = sys.argv, ['', 'fsck', '-d', self.tempdir]

        index_path = os.path.join(self.tempdir, 'index.json')
        with open(index_path) as f:
            data = json.load(f)

        entry1, entry2 = list(data.values())[:2]
        entry1['id'], entry2['id'] = entry2['id'], entry1['id']
        with open(index_path, 'w') as f:
            json.dump(data, f)

        try:
            with self.assertRaises(SystemExit) as cm:
                with capture(main) as (out, err, ret):
                    self.assertIn('ERROR', err)
                    self.assertIn('Id missmatch', err)
            self.assertEqual(cm.exception.code, 1)
        finally:
            sys.arv = argv

    def testIndexWithWrongCueIn(self):
        from klangbecken import main
        argv, sys.argv = sys.argv, ['', 'fsck', '-d', self.tempdir]

        index_path = os.path.join(self.tempdir, 'index.json')
        with open(index_path) as f:
            data = json.load(f)

        entry = next(iter(data.values()))
        entry['cue_in'], entry['cue_out'] = entry['cue_out'], entry['cue_in']

        with open(index_path, 'w') as f:
            json.dump(data, f)

        try:
            with self.assertRaises(SystemExit) as cm:
                with capture(main) as (out, err, ret):
                    self.assertIn('ERROR', err)
                    self.assertIn('cue_in larger than cue_out', err)
            self.assertEqual(cm.exception.code, 1)
        finally:
            sys.arv = argv

    def testIndexWithWrongCueOut(self):
        from klangbecken import main
        argv, sys.argv = sys.argv, ['', 'fsck', '-d', self.tempdir]

        index_path = os.path.join(self.tempdir, 'index.json')
        with open(index_path) as f:
            data = json.load(f)

        entry = next(iter(data.values()))
        entry['cue_out'], entry['length'] = entry['length'], entry['cue_out']

        with open(index_path, 'w') as f:
            json.dump(data, f)

        try:
            with self.assertRaises(SystemExit) as cm:
                with capture(main) as (out, err, ret):
                    self.assertIn('ERROR', err)
                    self.assertIn('cue_out larger than length', err)
            self.assertEqual(cm.exception.code, 1)
        finally:
            sys.arv = argv

    def testIndexMissingEntries(self):
        from klangbecken import main
        argv, sys.argv = sys.argv, ['', 'fsck', '-d', self.tempdir]

        index_path = os.path.join(self.tempdir, 'index.json')
        with open(index_path) as f:
            data = json.load(f)

        entry = next(iter(data.values()))
        del entry['cue_out']

        with open(index_path, 'w') as f:
            json.dump(data, f)

        try:
            with self.assertRaises(SystemExit) as cm:
                with capture(main) as (out, err, ret):
                    self.assertIn('ERROR', err)
                    self.assertIn('missing entries: cue_out', err)
            self.assertEqual(cm.exception.code, 1)
        finally:
            sys.arv = argv

    def testIndexTooManyEntries(self):
        from klangbecken import main
        argv, sys.argv = sys.argv, ['', 'fsck', '-d', self.tempdir]

        index_path = os.path.join(self.tempdir, 'index.json')
        with open(index_path) as f:
            data = json.load(f)

        entry = next(iter(data.values()))
        entry['whatever'] = 'whatever'

        with open(index_path, 'w') as f:
            json.dump(data, f)

        try:
            with self.assertRaises(SystemExit) as cm:
                with capture(main) as (out, err, ret):
                    self.assertIn('ERROR', err)
                    self.assertIn('too many entries: whatever', err)
            self.assertEqual(cm.exception.code, 1)
        finally:
            sys.arv = argv

    def testIndexMissingFile(self):
        from klangbecken import main
        argv, sys.argv = sys.argv, ['', 'fsck', '-d', self.tempdir]

        os.remove(os.path.join(self.music_dir, os.listdir(self.music_dir)[0]))

        try:
            with self.assertRaises(SystemExit) as cm:
                with capture(main) as (out, err, ret):
                    self.assertIn('ERROR', err)
                    self.assertIn('file does not exist', err)
            self.assertEqual(cm.exception.code, 1)
        finally:
            sys.arv = argv

    def testTagsValueMismatch(self):
        from klangbecken import main, SUPPORTED_FILE_TYPES
        argv, sys.argv = sys.argv, ['', 'fsck', '-d', self.tempdir]

        file_path = os.path.join(self.music_dir, os.listdir(self.music_dir)[0])
        FileType = SUPPORTED_FILE_TYPES['.' + file_path.split('.')[-1]]
        mutagenfile = FileType(file_path)
        mutagenfile['artist'] = 'Whatever'
        mutagenfile.save()

        try:
            with self.assertRaises(SystemExit) as cm:
                with capture(main) as (out, err, ret):
                    self.assertIn('ERROR', err)
                    self.assertIn("Tag value mismatch 'artist'", err)
            self.assertEqual(cm.exception.code, 1)
        finally:
            sys.arv = argv

    def testPlaylistWeightMismatch(self):
        from klangbecken import main
        argv, sys.argv = sys.argv, ['', 'fsck', '-d', self.tempdir]

        playlist_path = os.path.join(self.tempdir, 'music.m3u')
        with open(playlist_path) as f:
            lines = f.readlines()
        with open(playlist_path, 'w') as f:
            f.writelines(lines[::2])    # only write back every second line

        try:
            with self.assertRaises(SystemExit) as cm:
                with capture(main) as (out, err, ret):
                    self.assertIn('ERROR', err)
                    self.assertIn('Playlist weight mismatch', err)
            self.assertEqual(cm.exception.code, 1)
        finally:
            sys.arv = argv

    def testDanglingPlaylistEntries(self):
        from klangbecken import main
        argv, sys.argv = sys.argv, ['', 'fsck', '-d', self.tempdir]

        playlist_path = os.path.join(self.tempdir, 'music.m3u')
        with open(playlist_path, 'a') as f:
            f.write('music/not_an_uuid.mp3\n')

        try:
            with self.assertRaises(SystemExit) as cm:
                with capture(main) as (out, err, ret):
                    self.assertIn('ERROR', err)
                    self.assertIn('Dangling playlist entry', err)
                    self.assertIn('not_an_uuid', err)
            self.assertEqual(cm.exception.code, 1)
        finally:
            sys.arv = argv

    def testDanglingFiles(self):
        from klangbecken import main
        argv, sys.argv = sys.argv, ['', 'fsck', '-d', self.tempdir]

        with open(os.path.join(self.tempdir, 'music', 'not_an_uuid'), 'w'):
            pass

        try:
            with self.assertRaises(SystemExit) as cm:
                with capture(main) as (out, err, ret):
                    self.assertIn('ERROR', err)
                    self.assertIn('Dangling files', err)
                    self.assertIn('not_an_uuid', err)
            self.assertEqual(cm.exception.code, 1)
        finally:
            sys.arv = argv
