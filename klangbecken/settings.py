import mutagen.mp3

# Supported playlist names
PLAYLISTS = ("music", "classics", "jingles")

# Supported file types
# Map file extension to mutagen class for all supported file types
FILE_TYPES = {
    "mp3": mutagen.mp3.EasyMP3,
}

# Supported datetime format
# ISO8601 datetime with optional fraction of a second (milli- or microseconds) and
# mandatory timezone specification
ISO8601_TZ_AWARE_RE = (
    # Date
    r"(-?(?:[1-9][0-9]*)?[0-9]{4})-(1[0-2]|0[1-9])-(3[01]|0[1-9]|[12][0-9])T"
    # Time (optionally with a fraction of a second)
    r"(2[0-3]|[01][0-9]):([0-5][0-9]):([0-5][0-9])(\.[0-9]+)?"
    # Timezone information (+/- offset from UTC)
    r"[+-](?:2[0-3]|[01][0-9]):[0-5][0-9]"
)

# Supported Metadata
# Keys map to type (and contract) checks.
# A check can be a:
# - Type class (e.g. float)
# - Function taking one argument and returning True or False
#   (e.g. lambda x: x > 0 for positive numbers)
# - String interpreted as a regular expression. The checked values are
#   expected to be strings. (e.g. r"[1-9][0-9]{3}" for four digit zip codes)
# - List or tuple containing an arbitrary combination of the above.
#
# Note: The checks are evaluated in their specified order.
METADATA = {
    "id": r"^[a-z0-9]{8}-([a-z0-9]{4}-){3}[a-z0-9]{12}$",
    "ext": (str, lambda ext: ext in FILE_TYPES.keys()),
    "playlist": (str, lambda pl: pl in PLAYLISTS),
    "original_filename": str,
    "import_timestamp": ISO8601_TZ_AWARE_RE,
    "weight": (int, lambda c: c >= 0),
    "artist": str,
    "title": str,
    "track_gain": r"^[+-]?[0-9]+(\.[0-9]*) dB$",
    "cue_in": (float, lambda n: n >= 0.0),
    "cue_out": (float, lambda n: n >= 0.0),
    "play_count": (int, lambda n: n >= 0),
    "last_play": r"(^$)|(^{0}$)".format(ISO8601_TZ_AWARE_RE),
    "channels": (int, lambda n: n in (1, 2)),
    "samplerate": (int, lambda n: n in (44100, 48000)),
    "bitrate": (int, lambda n: n >= 128),
    "uploader": str,
    "expiration": r"(^$)|(^{0}$)".format(ISO8601_TZ_AWARE_RE),
}

# Metadata keys allowed for updates
UPDATE_KEYS = "artist title weight expiration".split()

# Metadata keys stored in the audio track (as ID3 tags)
TAG_KEYS = "artist title cue_in cue_out track_gain original_filename last_play".split()

# Metadata keys used for logging
LOG_KEYS = "id playlist original_filename artist title play_count last_play".split()

# Register additional ID3 tags
mutagen.easyid3.EasyID3.RegisterTXXXKey(key="cue_in", desc="CUE_IN")
mutagen.easyid3.EasyID3.RegisterTXXXKey(key="cue_out", desc="CUE_OUT")
mutagen.easyid3.EasyID3.RegisterTXXXKey(key="track_gain", desc="REPLAYGAIN_TRACK_GAIN")
mutagen.easyid3.EasyID3.RegisterTXXXKey(key="last_play", desc="LAST_PLAY")
mutagen.easyid3.EasyID3.RegisterTXXXKey(
    key="original_filename", desc="ORIGINAL_FILENAME"
)
