import pathlib
import random
import sys
import time

here = pathlib.Path(__file__).parent.resolve()
root = here.parent.parent
sys.path.append(str(root))

from klangbecken.player import LiquidsoapClient  # noqa: E402

print("Simulating the virtual Sämubox")
print("------------------------------", end="")

on_air = True
duration = 3

ls_client = LiquidsoapClient(str(root / "klangbecken.sock"))
with ls_client:
    ls_client.command("klangbecken.on_air True")

i = 0
while True:
    if i % 24 == 0:
        print(f"\nDay {i//24 + 1: >3}: ", end="")
    i += 1
    duration -= 1

    if on_air:
        print("+", end="", flush=True)
    else:
        print("_", end="", flush=True)

    if duration == 0:
        on_air = not on_air
        with ls_client:
            ls_client.command(f"klangbecken.on_air {on_air}")

        if on_air:
            duration = random.choice([1, 2, 3, 3, 4, 4, 5, 6])
        else:
            duration = random.choice([1, 1, 2, 2, 3, 4])

    time.sleep(36)  # Sleep for one "hour"
