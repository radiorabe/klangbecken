import re
import socket
import sys
import telnetlib

from werkzeug.exceptions import NotFound

from .settings import PLAYLISTS, SUPPORTED_FILE_TYPES


class LiquidsoapClient:
    """Liquidsoap Client.

    Use as context manager:
    with LiquidsoapClient('/var/run/liquidsoap.sock') as client:
        client.queue()


    Interactive mode
    >>> client = LiquidsoapClient()
    >>> client.open(("localhost", 1234))
    >>> client.info()
    ...
    >>> client.command('out.skip')
    ...
    """

    def __init__(self, path=None):
        if path is not None:
            self.path = path
        self.connected = False

    def __enter__(self):
        if not self.connected:
            self.open(self.path)
        self.log = []
        return self

    def __exit__(self, *exc_info):
        # Try to be nice
        try:
            self.tel.write(b"exit\n")
            self.tel.read_until(b"Bye!", timeout=0.1)
        finally:
            self.close()

            if exc_info[0]:
                for cmd, resp in self.log:
                    print("Command:", cmd, file=sys.stderr)
                    print("Response:", resp, file=sys.stderr)
                print("Exception:", *exc_info, file=sys.stderr)

            del self.log

    def open(self, addr):
        try:
            self.tel = UnixDomainTelnet(addr)
        except TypeError:
            self.tel = telnetlib.Telnet(*addr)

        self.connected = True

    def close(self):
        self.tel.close()
        self.connected = False

    def command(self, cmd):
        self.tel.write(cmd.encode("ascii", "ignore") + b"\n")
        ans = self.tel.read_until(b"END", timeout=0.1)
        if ans == b"":  # pragma: no cover
            raise ConnectionError(
                "Timeout while trying to read from player. Got no answer."
            )
        if not ans.endswith(b"END"):
            raise ConnectionError(
                f"Timeout while trying to read until 'END' from player. "
                f"Only got: {repr(ans)}"
            )
        ans = re.sub(b"[\r\n]*END$", b"", ans)
        ans = re.sub(b"^[\r\n]*", b"", ans)
        ans = re.subn(b"\r", b"", ans)[0]
        ans = ans.decode("ascii", "ignore").strip()
        if hasattr(self, "log"):
            self.log.append((cmd, ans))
        return ans

    def metadata(self, rid):
        ans = self.command(f"request.metadata {rid}")
        return dict(re.findall(r'^\s*(\S+?)="(.*?)"\s*$', ans, re.M))

    def info(self):
        from . import __version__

        info = {
            "uptime": self.command("uptime"),
            "liquidsoap_version": self.command("version"),
            "api_version": __version__,
        }
        for playlist in PLAYLISTS:
            lines = self.command(f"{playlist}.next").split("\n")[:2]
            lines = [line for line in lines if not line.startswith("[playing] ")]
            info[playlist] = _extract_id(lines[0], playlist) if lines else ""

        on_air = self.command("klangbecken.onair") == "true"
        info["on_air"] = on_air
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
        rid = self.command(f"queue.push {path}").strip()
        if self.metadata(rid)["status"] != "ready":  # pragma: no cover
            try:
                self.delete(rid)
            except Exception:
                pass
            raise LiquidsoapClientError("Queue push failed")

        return rid

    def delete(self, rid):
        if rid not in self.command("queue.secondary_queue").strip().split():
            raise NotFound(f"Track with QueueID '{rid}' not found.")

        ans = self.command(f"queue.remove {rid}")
        if ans.strip() != "OK" or self.metadata(rid)["status"] != "destroyed":
            raise LiquidsoapClientError("Queue delete failed")  # pragma: no cover


def _extract_id(filename, playlist=None):
    if playlist is None:
        playlist = r"(?:{})".format("|".join(PLAYLISTS))

    filename_re = r"^.*{0}/([0-9a-f-]+)\.(?:{1})$".format(
        playlist, "|".join(SUPPORTED_FILE_TYPES.keys())
    )
    try:
        return re.findall(filename_re, filename)[0]
    except IndexError:
        return ""


class LiquidsoapClientError(Exception):
    pass


class UnixDomainTelnet(telnetlib.Telnet):
    def __init__(self, path=None):
        super().__init__()
        if path is not None:
            self.open(path)

    def open(self, path):
        """Connect to a local UNIX domain socket."""
        self.eof = 0
        self.path = path
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(path)
