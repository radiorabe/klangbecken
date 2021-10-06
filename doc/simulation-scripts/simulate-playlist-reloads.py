import pathlib
import random
import sys
import time

here = pathlib.Path(__file__).parent.resolve()
root = here.parent.parent
sys.path.append(str(root))

from klangbecken.player import LiquidsoapClient  # noqa: E402

print("Simulating random playlist reloads")
print("----------------------------------")


client = LiquidsoapClient(str(root / "klangbecken.sock"))

intervals = (1, 1, 2, 2, 3, 3, 36, 37, 38, 800, 850, 900, 1000, 1100, 1200)
playlists = "music classics jingles".split()

i = 0
while True:
    i += 1
    with client:
        client.command(f"{random.choice(playlists)}.reload")
    print(".", end="", flush=True)

    if i % 24 == 0:
        print()

    time.sleep(random.choice(intervals))
