import re
import socket
import sys

from werkzeug.exceptions import NotFound

from .settings import FILE_TYPES, PLAYLISTS

metadata_re = re.compile(r'^\s*(\S+?)="(.*?)"\s*$', re.M)


class LiquidsoapClient:
    """Liquidsoap Client.

    Interact with a running Liquidsoap process through it's telnet interface.

    Use as context manager (preferred):
    >>> with LiquidsoapClient('/var/run/liquidsoap.sock') as client:
    ...    client.queue()


    Use interactively from Python console:
    >>> client = LiquidsoapClient()
    >>> client.open(("localhost", 1234))
    >>> client.info()
    ...
    >>> client.command('out.skip')
    ...
    """

    def __init__(self, path=None, timeout=0.2):
        self.path = path
        self.timeout = timeout
        self.connected = False

    def __enter__(self):
        if not self.connected:
            self.open(self.path, self.timeout)
        self.log = []
        return self

    def __exit__(self, *exc_info):
        # Try to be nice
        try:
            self.conn.write(b"exit\r\n")
            self.conn.read_until(b"Bye!")
        finally:
            self.close()

            if exc_info[0]:
                for cmd, resp in self.log:
                    print("Command:", cmd, file=sys.stderr)
                    print("Response:", resp, file=sys.stderr)
                print("Exception:", *exc_info, file=sys.stderr)

            del self.log

    def open(self, addr, timeout=0.2):
        self.conn = SocketConnection(addr, timeout)
        self.connected = True

    def close(self):
        self.conn.close()
        self.connected = False

    def command(self, cmd):
        """Execute a Liquidsoap command.

        Returns the response.
        """
        self.conn.write(cmd.encode("ascii", "ignore") + b"\r\n")
        ans = self.conn.read_until(b"\r\nEND")
        ans = re.sub(b"[\r\n]*END$", b"", ans)
        ans = re.sub(b"^[\r\n]*", b"", ans)
        ans = re.subn(b"\r", b"", ans)[0]
        ans = ans.decode("ascii", "ignore").strip()
        if hasattr(self, "log"):
            self.log.append((cmd, ans))
        return ans

    def metadata(self, rid):
        """Query metadata information for a Liquidsoap request[1].

        Returns dict with metadata information.

        [1] The scheduling of an audio track for playing is called a 'request'
            in Liquidsoap jargon.
        """
        ans = self.command(f"request.metadata {rid}")
        return dict(re.findall(metadata_re, ans))

    def info(self):
        """Query general information about the state of the player.

        * Versions and uptime
        * 'on air' state
        * Current track, if on air.
        * Next scheduled track for all playlists and the queue, if any.
        """
        from . import __version__

        info = {
            "uptime": self.command("uptime"),
            "liquidsoap_version": self.command("version"),
            "api_version": __version__,
            "python_version": sys.version.split()[0],
        }
        on_air = self.command("klangbecken.on_air").lower() == "true"
        info["on_air"] = on_air

        if on_air:
            for playlist in PLAYLISTS:
                lines = self.command(f"{playlist}.next").strip().split("\n")
                lines = [
                    line for line in lines if line and not line.startswith("[playing] ")
                ]
                info[playlist] = _extract_id(lines[0], playlist) if lines else ""
        else:
            for playlist in PLAYLISTS:
                info[playlist] = ""

        if on_air:
            on_air_rid = self.command("request.on_air").strip()
            if on_air_rid:
                metadata = self.metadata(on_air_rid)
                info["current_track"] = {
                    "source": metadata["source"],
                    "id": _extract_id(metadata["filename"]),
                }
            else:
                info["current_track"] = {}

        queue = (
            self.metadata(rid) for rid in self.command("queue.queue").strip().split()
        )

        queue = (entry for entry in queue if entry["status"] == "ready")
        entry = next(queue, None)
        info["queue"] = _extract_id(entry["filename"]) if entry else ""

        return info

    def queue(self):
        """List the contents of the queue."""
        queue = [
            self.metadata(rid) for rid in self.command("queue.queue").strip().split()
        ]
        for entry in queue:
            if entry["status"] not in ("playing", "ready"):  # pragma: no cover
                print(
                    f"WARNING: Queue entry ({entry['rid']}: {entry['filename']} with "
                    f"invalid status: {entry['status']}",
                    file=sys.stderr,
                )

        queue = [entry for entry in queue if entry["status"] == "ready"]
        queue = [
            {
                "id": _extract_id(entry["filename"]),
                "queue_id": entry["rid"],
                "queue": entry["queue"],
            }
            for entry in queue
        ]
        return queue

    def push(self, path):
        """Add a new track to the queue.

        Returns the request id for the added track.
        """
        rid = self.command(f"queue.push {path}").strip()
        if self.metadata(rid)["status"] != "ready":  # pragma: no cover
            try:
                self.delete(rid)
            except Exception:
                pass
            raise LiquidsoapClientQueueError("Queue push failed")

        return rid

    def delete(self, rid):
        """Delete track from the queue."""
        if rid not in self.command("queue.secondary_queue").strip().split():
            raise NotFound(f"Track with QueueID '{rid}' not found.")

        ans = self.command(f"queue.remove {rid}")
        if ans.strip() != "OK" or self.metadata(rid)["status"] != "destroyed":
            raise LiquidsoapClientQueueError("Queue delete failed")  # pragma: no cover


filename_res = {
    playlist: re.compile(
        r"^.*{0}/([0-9a-f-]+)\.(?:{1})$".format(playlist, "|".join(FILE_TYPES.keys()))
    )
    for playlist in PLAYLISTS
}

filename_res[None] = re.compile(
    r"^.*(?:{0})/([0-9a-f-]+)\.(?:{1})$".format(
        "|".join(PLAYLISTS), "|".join(FILE_TYPES.keys())
    )
)


def _extract_id(filename, playlist=None):
    return re.findall(filename_res[playlist], filename)[0]


class LiquidsoapClientQueueError(Exception):
    pass


class SocketConnection:
    def __init__(self, addr=None, timeout=None):
        self.in_data = b""
        if addr is not None:
            self.open(addr, timeout)

    def open(self, addr, timeout=None):
        if isinstance(addr, str):   # Path to UNIX domain socket
            try:
                self.sock = socket.socket(socket.AF_UNIX)
                self.sock.connect(addr)
                self.sock.settimeout(timeout)
            except OSError:
                try:
                    self.sock.close()
                finally:
                    pass
                raise
        else:                      # IP-Address and Port
            self.sock = socket.create_connection(addr, timeout)

    def write(self, data):
        self.sock.send(data)

    def read_until(self, expected):
        while expected not in self.in_data:
            self.in_data += self.sock.recv(128)
        expected_end = self.in_data.index(expected) + len(expected)
        data = self.in_data[:expected_end]
        self.in_data = self.in_data[expected_end:]
        return data

    def close(self):
        self.sock.close()
