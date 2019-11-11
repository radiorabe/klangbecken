# -*- coding: utf-8 -*-
from __future__ import unicode_literals, print_function

import json
import mock
import os
import shutil
import sys
import tempfile
import unittest

from .utils import capture


class ImporterTestCase(unittest.TestCase):
    def setUp(self):
        from klangbecken_api import check_and_crate_data_dir
        self.current_path = os.path.dirname(os.path.realpath(__file__))
        self.tempdir = tempfile.mkdtemp()
        self.music_dir = os.path.join(self.tempdir, 'music')
        self.jingles_dir = os.path.join(self.tempdir, 'jingles')
        check_and_crate_data_dir(self.tempdir)

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def testImport(self):
        from klangbecken_api import import_files
        audio_path = os.path.join(self.current_path, 'audio')
        audio1_path = os.path.join(audio_path, 'silence.mp3')
        audio2_path = os.path.join(audio_path, 'padded.ogg')
        audio1_mtime = os.stat(audio1_path).st_mtime

        argv, sys.argv = sys.argv, ['', self.tempdir, 'music']
        try:
            # Import nothing -> usage
            with self.assertRaises(SystemExit) as cm:
                with capture(import_files, False) as (out, err, ret):
                    self.assertIn('Usage', err)
            self.assertEqual(cm.exception.code, 1)

            # Import one file
            sys.argv.append(audio1_path)
            with self.assertRaises(SystemExit) as cm:
                with capture(import_files, False) as (out, err, ret):
                    self.assertIn('Successfully imported 1 of 1 files.', out)
            self.assertEqual(cm.exception.code, 0)

            files = [f for f in os.listdir(self.music_dir)
                     if os.path.isfile(os.path.join(self.music_dir, f))]
            self.assertEqual(len(files), 1)
            with open(os.path.join(self.tempdir, 'index.json')) as file:
                data = json.load(file)
                self.assertEqual(len(data.keys()), 1)
                self.assertEqual(list(data.values())[0]['import_timestamp'],
                                 audio1_mtime)
                self.assertEqual(list(data.values())[0]['original_filename'],
                                 'silence.mp3')

            # Import two file
            sys.argv.append(audio2_path)
            with self.assertRaises(SystemExit) as cm:
                with capture(import_files, False) as (out, err, ret):
                    self.assertIn('Successfully imported 2 of 2 files.', out)
            self.assertEqual(cm.exception.code, 0)

            files = [f for f in os.listdir(self.music_dir)  # pragma: no cover
                     if os.path.isfile(os.path.join(self.music_dir, f))]
            self.assertEqual(len(files), 3)
            with open(os.path.join(self.tempdir, 'index.json')) as file:
                self.assertEqual(len(json.load(file).keys()), 3)

            # Try importing inexistent file
            sys.argv.append('inexistent')
            with self.assertRaises(SystemExit) as cm:
                with capture(import_files, False) as (out, err, ret):
                    self.assertIn('Successfully imported 2 of 3 files.', out)
                    self.assertIn('WARNING', err)
            self.assertEqual(cm.exception.code, 1)

            # Try importing into inexistent playlist
            sys.argv = ['', self.tempdir, 'nonexistentplaylist', audio1_path]
            with self.assertRaises(SystemExit) as cm:
                with capture(import_files, False) as (out, err, ret):
                    self.assertEqual(out.strip(), '')
                    self.assertIn('ERROR', err)
            self.assertEqual(cm.exception.code, 1)

            # Try importing into inexistent data dir
            sys.argv = ['', 'nonexistentdatadir', 'music', audio2_path]
            with self.assertRaises(SystemExit) as cm:
                with capture(import_files, False) as (out, err, ret):
                    self.assertEqual(out.strip(), '')
                    self.assertIn('ERROR', err)
            self.assertEqual(cm.exception.code, 1)

            # Incomplete command
            sys.argv = ['', self.tempdir]
            with self.assertRaises(SystemExit) as cm:
                with capture(import_files, False) as (out, err, ret):
                    self.assertEqual(out.strip(), '')
                    self.assertIn('Usage', err)
            self.assertEqual(cm.exception.code, 1)

            path = os.path.join(self.tempdir, 'file.wmv')
            with open(path, 'w'):
                pass

            # Try importing unsupported file type
            sys.argv = ['', self.tempdir, 'music', path]
            with self.assertRaises(SystemExit) as cm:
                with capture(import_files, False) as (out, err, ret):
                    self.assertIn('Successfully imported 0 of 1 files.', out)
                    self.assertIn('WARNING', err)
            self.assertEqual(cm.exception.code, 1)

        finally:
            sys.argv = argv

    @mock.patch('klangbecken_api.input', return_value='y')
    def testImportInteractiveYes(self, input):
        from klangbecken_api import import_files

        audio_path = os.path.join(self.current_path, 'audio')
        audio1_path = os.path.join(audio_path, 'silence.mp3')

        argv, sys.argv = sys.argv, ['', self.tempdir, 'music']
        try:

            sys.argv = ['', self.tempdir, 'music', audio1_path]
            with self.assertRaises(SystemExit) as cm:
                with capture(import_files) as (out, err, ret):
                    self.assertIn('Successfully analyzed 1 of 1 files.', out)
                    self.assertIn('Successfully imported 1 of 1 files.', out)
                    music_dir = os.path.join(self.tempdir, 'music')
                    file_count = len(os.listdir(music_dir))
                    self.assertEqual(file_count, 1)
            self.assertEqual(cm.exception.code, 0)

        finally:
            sys.argv = argv

    @mock.patch('klangbecken_api.input', return_value='n')
    def testImportInteractiveNo(self, input):
        from klangbecken_api import import_files

        audio_path = os.path.join(self.current_path, 'audio')
        audio1_path = os.path.join(audio_path, 'silence.mp3')

        argv, sys.argv = sys.argv, ['', self.tempdir, 'music']
        try:

            sys.argv = ['', self.tempdir, 'music', audio1_path]
            with self.assertRaises(SystemExit) as cm:
                with capture(import_files) as (out, err, ret):
                    self.assertIn('Successfully analyzed 1 of 1 files.', out)
                    self.assertIn('Successfully imported 0 of 1 files.', out)
                    music_dir = os.path.join(self.tempdir, 'music')
                    file_count = len(os.listdir(music_dir))
                    self.assertEqual(file_count, 0)
            self.assertEqual(cm.exception.code, 1)

        finally:
            sys.argv = argv
