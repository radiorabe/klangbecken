import os
import subprocess
from random import choice, gauss, random

from mutagen import File

if not os.path.isdir("./sim-data"):
    os.mkdir("./sim-data")

if len(os.listdir("./sim-data")) > 0:
    print("ERROR: 'sim-data' directory not empty")
    exit(1)

colors = ("white", "pink", "brown", "blue", "violet", "velvet")
bitrates = (128, 160, 192, 256, 320, 320, 320)
samplerates = (44100, 48000)

playlists = {
    "music": {
        "number_of_tracks": 1334,
        "length_avg": 2.3,
        "length_stdev": 0.7,
        "length_min": 0.3,
        "length_max": 6.1,
        "freq": 880,
        "generator": "sine=f={freq}:r={samplerate}:d={duration},stereotools",
        "title": "{i:0>4} ({duration:.2f} s, {freq:.0f} Hz)",
    },
    "classics": {
        "number_of_tracks": 1280,
        "length_avg": 2.4,
        "length_stdev": 0.7,
        "length_min": 0.45,
        "length_max": 9.7,
        "freq": 440,
        "generator": "sine=f={freq}:r={samplerate}:d={duration},stereotools",
        "title": "{i:0>4} ({duration:.2f} s, {freq:.0f} Hz)",
    },
    "jingles": {
        "number_of_tracks": 22,
        "length_avg": 0.12,
        "length_stdev": 0.17,
        "length_min": 0.03,
        "length_max": 0.8,
        "freq": 0,
        "generator": "anoisesrc=d={duration}:c={color}:r={samplerate},stereotools",
        "title": "{i:0>4} ({duration:.2f} s, {color} noise)",
    },
}

for playlist, config in playlists.items():
    for i in range(1, config["number_of_tracks"] + 1):
        duration = 0
        while not (config["length_min"] < duration < config["length_max"]):
            duration = gauss(config["length_avg"], config["length_stdev"])

        freq = config["freq"] + (random() - 0.5) * 160
        color = choice(colors)
        bitrate = choice(bitrates)
        samplerate = choice(samplerates)
        filename = f"./sim-data/{playlist}-{i:0>4}.mp3"
        subprocess.check_call(
            [
                *"ffmpeg -hide_banner -loglevel panic -filter_complex".split(),
                config["generator"].format(**config, **locals()),
                *"-c:a libmp3lame -b:a".split(),
                f"{bitrate}k",
                filename,
            ]
        )
        f = File(filename, easy=True)
        f["artist"] = f"{playlist.capitalize()}"
        f["title"] = config["title"].format(**config, **locals())
        f.save()
