import os
import random
import shutil
import socket
import socketserver
import tempfile
import threading
import unittest
from unittest import mock

from werkzeug.exceptions import NotFound


class EchoHandler(socketserver.BaseRequestHandler):
    def handle(self):
        while True:
            msg = self.request.recv(8192)
            if not msg or msg.strip() == b"exit":
                self.request.send(b"Bye!\n")
                break
            self.request.send(msg)


def get_port():
    while True:
        port = random.randrange(1024, 65535)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("localhost", port))
            sock.close()
            return port
        except OSError:
            pass


class LiquidsoapClientTestCase(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def testOpenAndUnix(self):
        from klangbecken.player import LiquidsoapClient

        settings = [
            (socketserver.TCPServer, ("localhost", get_port())),
            (socketserver.UnixStreamServer, os.path.join(self.tempdir, "test.sock")),
        ]
        for Server, addr in settings:
            with Server(addr, EchoHandler) as serv:
                thread = threading.Thread(target=serv.serve_forever)
                thread.start()
                client = LiquidsoapClient(addr)
                with client:
                    result = client.command("\r\n\r\nhello\r\nworld\r\n\r\nEND")
                self.assertEqual(result, "hello\nworld")
                with client:
                    with self.assertRaises(ConnectionError) as cm:
                        client.command("Does not contain the finishing sentinel.")
                self.assertIn(
                    "Timeout while trying to read until", cm.exception.args[0]
                )
                serv.shutdown()
                thread.join()

    def testCommandLoggingOnError(self):
        from klangbecken.player import LiquidsoapClient

        from .utils import capture

        Server = socketserver.UnixStreamServer
        addr = os.path.join(self.tempdir, "test.sock")
        with Server(addr, EchoHandler) as serv:
            thread = threading.Thread(target=serv.serve_forever)
            thread.start()
            client = LiquidsoapClient(addr)

            def do():
                with client:
                    client.command("\r\n\r\nhello\r\nworld\r\n\r\nEND")
                    raise Exception("Something terrible happened")

            with self.assertRaises(Exception) as cm:
                with capture(do) as (out, err, ret):
                    pass
            self.assertEqual("Something terrible happened", cm.exception.args[0])
            self.assertIn("Something terrible happened", err)
            self.assertIn("Command:", err)
            self.assertIn("Response:", err)
            self.assertIn("hello", err)

            serv.shutdown()
            thread.join()

    def testMetadata(self):
        from klangbecken.player import LiquidsoapClient

        client = LiquidsoapClient()
        client.command = mock.Mock(
            return_value='rid="15"\ntitle="title"\nartist="artist"'
        )

        result = client.metadata(15)
        client.command.assert_called_once_with("request.metadata 15")
        self.assertEqual(result, {"rid": "15", "artist": "artist", "title": "title"})

    def testInfoOnAir(self):
        from klangbecken import __version__
        from klangbecken.player import LiquidsoapClient

        command_calls = [
            ("uptime", "0d 00h 08m 54s"),
            ("version", "Liquidsoap 1.4.2"),
            ("klangbecken.on_air", "true"),
            (
                "music.next",
                "[ready] data/music/2e3fc9b6-36ee-4640-9efd-cdf10560adb4.mp3",
            ),
            (
                "classics.next",
                """[playing] data/classics/4daabe44-6d48-47c4-a187-592cf048b039.mp3""",
            ),
            ("jingles.next", ""),
            ("request.on_air", "8"),
            (
                "request.metadata 8",
                '''playlist_position="1"
                rid="8"
                source="classics"
                temporary="false"
                filename="data/classics/4daabe44-6d48-47c4-a187-592cf048b039.mp3"''',
            ),
            ("queue.queue", "0 1"),
            (
                "request.metadata 0",
                '''queue="primary"
                rid="0"
                status="ready"
                source="queue"
                temporary="false"
                filename="data/classics/4daabe44-6d48-47c4-a187-592cf048b039.mp3"''',
            ),
        ]

        def side_effect(actual_command):
            command, result = command_calls.pop(0)
            self.assertEqual(command, actual_command)
            return result

        client = LiquidsoapClient()
        client.command = mock.Mock(side_effect=side_effect)

        result = client.info()
        self.assertEqual(
            result,
            {
                "uptime": "0d 00h 08m 54s",
                "liquidsoap_version": "Liquidsoap 1.4.2",
                "api_version": __version__,
                "music": "2e3fc9b6-36ee-4640-9efd-cdf10560adb4",
                "classics": "",
                "jingles": "",
                "on_air": True,
                "current_track": {
                    "source": "classics",
                    "id": "4daabe44-6d48-47c4-a187-592cf048b039",
                },
                "queue": "4daabe44-6d48-47c4-a187-592cf048b039",
            },
        )
        self.assertEqual(command_calls, [])

    def testInfoOnAirNoCurrentTrack(self):
        from klangbecken import __version__
        from klangbecken.player import LiquidsoapClient

        command_calls = [
            ("uptime", "0d 00h 08m 54s"),
            ("version", "Liquidsoap 1.4.2"),
            ("klangbecken.on_air", "true"),
            (
                "music.next",
                "[ready] data/music/2e3fc9b6-36ee-4640-9efd-cdf10560adb4.mp3",
            ),
            (
                "classics.next",
                "[playing] data/classics/4daabe44-6d48-47c4-a187-592cf048b039.mp3",
            ),
            ("jingles.next", ""),
            ("request.on_air", ""),
            ("queue.queue", "0 1"),
            (
                "request.metadata 0",
                '''queue="primary"
                rid="0"
                status="ready"
                source="queue"
                temporary="false"
                filename="data/classics/4daabe44-6d48-47c4-a187-592cf048b039.mp3"''',
            ),
        ]

        def side_effect(actual_command):
            command, result = command_calls.pop(0)
            self.assertEqual(command, actual_command)
            return result

        client = LiquidsoapClient()
        client.command = mock.Mock(side_effect=side_effect)

        result = client.info()
        self.assertEqual(
            result,
            {
                "uptime": "0d 00h 08m 54s",
                "liquidsoap_version": "Liquidsoap 1.4.2",
                "api_version": __version__,
                "music": "2e3fc9b6-36ee-4640-9efd-cdf10560adb4",
                "classics": "",
                "jingles": "",
                "on_air": True,
                "current_track": {},
                "queue": "4daabe44-6d48-47c4-a187-592cf048b039",
            },
        )
        self.assertEqual(command_calls, [])

    def testInfoOffAir(self):
        from klangbecken import __version__
        from klangbecken.player import LiquidsoapClient

        command_calls = [
            ("uptime", "0d 00h 08m 54s"),
            ("version", "Liquidsoap 1.4.2"),
            ("klangbecken.on_air", "false"),
            ("queue.queue", "0 1"),
            (
                "request.metadata 0",
                '''queue="primary"
                rid="0"
                status="ready"
                source="queue"
                temporary="false"
                filename="data/classics/4daabe44-6d48-47c4-a187-592cf048b039.mp3"''',
            ),
            (
                "request.metadata 1",
                '''queue="secondary"
                rid="1"
                status="ready"
                source="queue"
                temporary="false"
                filename="data/classics/4daabe44-6d48-47c4-a187-592cf048b039.mp3"''',
            ),
        ]

        def side_effect(actual_command):
            command, result = command_calls.pop(0)
            self.assertEqual(command, actual_command)
            return result

        client = LiquidsoapClient()
        client.command = mock.Mock(side_effect=side_effect)
        result = client.info()
        self.assertEqual(
            result,
            {
                "uptime": "0d 00h 08m 54s",
                "liquidsoap_version": "Liquidsoap 1.4.2",
                "api_version": __version__,
                "on_air": False,
                "music": "",
                "classics": "",
                "jingles": "",
                "queue": "4daabe44-6d48-47c4-a187-592cf048b039",
            },
        )
        # self.assertEqual(command_calls, [])

    def testQueue(self):
        from klangbecken.player import LiquidsoapClient

        command_calls = [
            ("queue.queue", "0 1"),
            (
                "request.metadata 0",
                '''queue="primary"
                rid="0"
                status="ready"
                source="queue"
                temporary="false"
                filename="data/classics/4daabe44-6d48-47c4-a187-592cf048b039.mp3"''',
            ),
            (
                "request.metadata 1",
                '''queue="secondary"
                rid="1"
                status="ready"
                source="queue"
                temporary="false"
                filename="data/classics/4daabe44-6d48-47c4-a187-592cf048b039.mp3"''',
            ),
        ]

        def side_effect(actual_command):
            command, result = command_calls.pop(0)
            self.assertEqual(command, actual_command)
            return result

        client = LiquidsoapClient()
        client.command = mock.Mock(side_effect=side_effect)

        result = client.queue()
        self.assertEqual(
            result,
            [
                {
                    "id": "4daabe44-6d48-47c4-a187-592cf048b039",
                    "queue_id": "0",
                    "queue": "primary",
                },
                {
                    "id": "4daabe44-6d48-47c4-a187-592cf048b039",
                    "queue_id": "1",
                    "queue": "secondary",
                },
            ],
        )
        self.assertEqual(command_calls, [])

    def testPush(self):
        from klangbecken.player import LiquidsoapClient

        command_calls = [
            ("queue.push data/classics/4daabe44-6d48-47c4-a187-592cf048b039.mp3", "1"),
            (
                "request.metadata 1",
                '''queue="primary"
                rid="1"
                status="ready"
                source="queue"
                temporary="false"
                filename="data/classics/4daabe44-6d48-47c4-a187-592cf048b039.mp3"''',
            ),
        ]

        def side_effect(actual_command):
            command, result = command_calls.pop(0)
            self.assertEqual(command, actual_command)
            return result

        client = LiquidsoapClient()
        client.command = mock.Mock(side_effect=side_effect)
        result = client.push("data/classics/4daabe44-6d48-47c4-a187-592cf048b039.mp3")
        self.assertEqual(result, "1")
        self.assertEqual(command_calls, [])

    def testDelete(self):
        from klangbecken.player import LiquidsoapClient

        command_calls = [
            ("queue.secondary_queue", "2 4"),
            ("queue.remove 2", "OK"),
            (
                "request.metadata 2",
                '''queue="secondary"
                rid="2"
                status="destroyed"
                source="queue"
                temporary="false"
                filename="data/classics/4daabe44-6d48-47c4-a187-592cf048b039.mp3"''',
            ),
        ]

        def side_effect(actual_command):
            command, result = command_calls.pop(0)
            self.assertEqual(command, actual_command)
            return result

        client = LiquidsoapClient()
        client.command = mock.Mock(side_effect=side_effect)
        client.delete("2")
        self.assertEqual(command_calls, [])

    def testDeleteNotFound(self):
        from klangbecken.player import LiquidsoapClient

        command_calls = [
            ("queue.secondary_queue", "2 4"),
            # Should not be called:
            # ("queue.remove 3", "ERROR: No such request in queue!"),
        ]

        def side_effect(actual_command):
            command, result = command_calls.pop(0)
            self.assertEqual(command, actual_command)
            return result

        client = LiquidsoapClient()
        client.command = mock.Mock(side_effect=side_effect)
        with self.assertRaises(NotFound):
            client.delete("3")
        self.assertEqual(command_calls, [])
