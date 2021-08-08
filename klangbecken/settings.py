import mutagen.mp3

PLAYLISTS = ("music", "classics", "jingles")

# Map file extension to mutagen class for all supported file types
SUPPORTED_FILE_TYPES = {
    "mp3": mutagen.mp3.EasyMP3,
}

ISO8601_RE = (
    # Date
    r"(-?(?:[1-9][0-9]*)?[0-9]{4})-(1[0-2]|0[1-9])-(3[01]|0[1-9]|[12][0-9])T"
    # Time (optionally with a fraction of a second)
    r"(2[0-3]|[01][0-9]):([0-5][0-9]):([0-5][0-9])(\.[0-9]+)?"
    # Timezone information (Z for UTC or +/- offset from UTC)
    r"(Z|[+-](?:2[0-3]|[01][0-9]):[0-5][0-9])?"
)

ALLOWED_METADATA = {
    "id": (str, r"^[a-z0-9]{8}-([a-z0-9]{4}-){3}[a-z0-9]{12}$"),
    "ext": (str, lambda ext: ext in SUPPORTED_FILE_TYPES.keys()),
    "playlist": (str, lambda pl: pl in PLAYLISTS),
    "original_filename": str,
    "import_timestamp": ISO8601_RE,
    "weight": (int, lambda c: c >= 0),
    "artist": str,
    "title": str,
    "track_gain": (str, r"^[+-]?[0-9]+(\.[0-9]*) dB$"),
    "cue_in": (float, lambda n: n >= 0.0),
    "cue_out": (float, lambda n: n >= 0.0),
    "play_count": (int, lambda n: n >= 0),
    "last_play": (str, r"(^$)|(^{0}$)".format(ISO8601_RE)),
    "last_play_epoch": (float, lambda n: n >= 0.0),
    "channels": (int, lambda n: n in (1, 2)),
    "samplerate": (int, lambda n: n in (44100, 48000)),
    "bitrate": (int, lambda n: n >= 128),
    "uploader": str,
}

UPDATE_KEYS = "artist title weight".split()

TAG_KEYS = (
    "artist title cue_in cue_out track_gain original_filename last_play_epoch"
).split()

LOG_KEYS = "id playlist original_filename artist title play_count last_play".split()

mutagen.easyid3.EasyID3.RegisterTXXXKey(key="cue_in", desc="CUE_IN")
mutagen.easyid3.EasyID3.RegisterTXXXKey(key="cue_out", desc="CUE_OUT")
mutagen.easyid3.EasyID3.RegisterTXXXKey(key="track_gain", desc="REPLAYGAIN_TRACK_GAIN")
mutagen.easyid3.EasyID3.RegisterTXXXKey(
    key="original_filename", desc="ORIGINAL_FILENAME"
)
mutagen.easyid3.EasyID3.RegisterTXXXKey(key="last_play_epoch", desc="LAST_PLAY_EPOCH")
