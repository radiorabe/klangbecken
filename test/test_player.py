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
            # self.request.send(b"echo: ")
            # time.sleep(0.5)
            self.request.send(msg)


# port = random.randrange(1024, 100000)
# serv = socketserver.TCPServer(("localhost", port), EchoHandler)
# thread = threading.Thread(target=serv.serve_forever)
# thread.start()
# tel = telnetlib.Telnet("localhost", port)


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
        from klangbecken.player import LiquidsoapClient, LiquidsoapClientError

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
            (
                "music.next",
                """[ready] data/music/2e3fc9b6-36ee-4640-9efd-cdf10560adb4.mp3
                [ready] data/music/3819cd8d-cb4b-49e0-8710-e091bb7dd4dd.mp3
                data/music/b78cc27d-e4a5-40d5-852e-a2a9f641a490.mp3
                data/music/5bf6bd2d-4506-4f06-be04-7c4145fb06e9.mp3""",
            ),
            (
                "classics.next",
                """[playing] data/classics/4daabe44-6d48-47c4-a187-592cf048b039.mp3""",
            ),
            (
                "jingles.next",
                """[ready] data/jingles/4c4903fe-7c1f-4dbf-925c-a43a9ac1e55f.mp3
                [ready] data/jingles/86fde5f3-47aa-4ac7-ad47-bfc82612224f.mp3
                data/jingles/17e716e1-8a03-4a1f-bb40-7d8d90e97f98.mp3
                data/jingles/c5ed6706-fb81-49ca-b1bb-4eaf19e598a6.mp3
                data/jingles/9637b1e1-6542-4715-bb02-00b433011551.mp3""",
            ),
            ("klangbecken.onair", "true"),
            ("request.on_air", "8"),
            (
                "request.metadata 8",
                '''playlist_position="1"
                rid="8"
                source="classics"
                temporary="false"
                filename="data/classics/4daabe44-6d48-47c4-a187-592cf048b039.mp3"''',
            ),
            ("out.remaining", "1165.97"),
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
                "jingles": "4c4903fe-7c1f-4dbf-925c-a43a9ac1e55f",
                "on_air": {
                    "source": "classics",
                    "id": "4daabe44-6d48-47c4-a187-592cf048b039",
                    "remaining": 1165.97,
                },
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
            (
                "music.next",
                """[ready] data/music/2e3fc9b6-36ee-4640-9efd-cdf10560adb4.mp3
                [ready] data/music/3819cd8d-cb4b-49e0-8710-e091bb7dd4dd.mp3
                data/music/b78cc27d-e4a5-40d5-852e-a2a9f641a490.mp3""",
            ),
            (
                "classics.next",
                """[playing] data/classics/4daabe44-6d48-47c4-a187-592cf048b039.mp3
                [ready] data/classics/49080554-1a0f-41a4-9f00-f1158c2bd7e5.mp3
                data/classics/4fbf6158-7d18-47e1-b9a4-fa3f3cf1d15b.mp3""",
            ),
            (
                "jingles.next",
                """[ready] data/jingles/4c4903fe-7c1f-4dbf-925c-a43a9ac1e55f.mp3
                [ready] data/jingles/86fde5f3-47aa-4ac7-ad47-bfc82612224f.mp3
                data/jingles/17e716e1-8a03-4a1f-bb40-7d8d90e97f98.mp3""",
            ),
            ("klangbecken.onair", "false"),
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
                "music": "2e3fc9b6-36ee-4640-9efd-cdf10560adb4",
                "classics": "49080554-1a0f-41a4-9f00-f1158c2bd7e5",
                "jingles": "4c4903fe-7c1f-4dbf-925c-a43a9ac1e55f",
                "on_air": {},
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
