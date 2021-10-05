from klangbecken.api import klangbecken_api

with open("/etc/klangbecken.conf") as f:
    config = dict(
        line.rstrip()[len("KLANGBECKEN_") :].split("=", 1)
        for line in f.readlines()
        if line.startswith("KLANGBECKEN_")
    )

application = klangbecken_api(
    config["API_SECRET"], config["DATA_DIR"], config["PLAYER_SOCKET"]
)
