import os

from .settings import PLAYLISTS


def _check_data_dir(data_dir, create=False):
    """Create local data directory structure for testing and development."""
    for path in [data_dir, os.path.join(data_dir, "log")] + [
        os.path.join(data_dir, playlist) for playlist in PLAYLISTS
    ]:
        if not os.path.isdir(path):
            if create:
                os.mkdir(path)
            else:
                raise Exception(f"Directory '{path}' does not exist")
    for path in [os.path.join(data_dir, d + ".m3u") for d in PLAYLISTS + ("prio",)]:
        if not os.path.isfile(path):
            if create:
                with open(path, "a"):
                    pass
            else:
                raise Exception(f"Playlist '{path}'' does not exist")
    path = os.path.join(data_dir, "index.json")
    if not os.path.isfile(path):
        if create:
            with open(path, "w") as f:
                f.write("{}")
        else:
            raise Exception('File "index.json" does not exist')
