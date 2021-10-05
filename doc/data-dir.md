# Data Directory

## Audio Files

Every track is identified by
* a playlist, in which it appears
* a UUID
* a valid file extension

For every playlist, there is a directory containing all the audio files. A track cannot be shared between multiple playlists.

When uploading a new audio track, the file is temporarily stored in the `upload` directory for analysis. Upon success, the file is then moved to the corresponding playlist folder. The UUID and extension are used for it's filename.

Apart from track title and artist name, additional metadata information is stored directly in the audio files metadata tags:
* Cue points (`cue_in` and `cue_out`)
* Loudness information (`track_gain`)
* A timestamp of the last play (`last_play`)
* The original filename (`original_filename`)

The cue points, loudness information, and last play timestamp are used by the liquidsoap player for playback. The original filename is stored for debugging purpose.

Audio file metadata tags can be extracted with the `mutagen-inspect` command line util.

## Playlist Files

Tracks can be _activated_ and _deactivated_ by adding them to the playlist file of the corresponding playlist. A track can be added multiple times to the playlist file to increase it's priority (or `weight`).

The playlist file is a simple text file in the M3U format. An entry in the playlist is a single line, with the relative path to the audio track. There is one playlist file for every playlist.

## Log Files

The `log` directory contains monthly play log files in the CVS format. The file UUID, playlist name, original filename, artist name, track title, total play count, and last play timestamp are logged.

## Metadata Cache

The file `index.json` caches all metadata information in the JSON format.

For every track the following information is stored in an object under the file UUID key:
- `id`: File UUID
- `ext`: File type/extension (currently only `mp3` is supported)
- `playlist`: Name of the playlist
- `original_filename`: Original filename of the uploaded file
- `import_timestamp`: Date and time when the file was uploaded or imported (ISO8601 timestamp)
- `weight`: Priority or weight of the track, or how many times it appears in the playlist file (can be zero)
- `artist`: Artist name
- `title`: Track title
- `track_gain`: ReplayGain track gain (in dB)
- `cue_in`: Cue in point (in seconds)
- `cue_out`: Cue out point (in seconds)
- `play_count`: Total play count
- `last_play`: Date and time of the last play if the track has been played at least once (ISO8601 timestamp or empty string)
- `channels`: Number of channels (1: mono, 2: stereo)
- `samplerate`: Sample rate (44.1 or 48 kHz)
- `bitrate`: Bitrate of the encoded stream
- `uploader`: Username of the person uploading the file
- `expiration`: Date and time after which this track should be disabled (ISO8601 timestamp or empty string)

Information in the metadata cache (except for the `uploader` and `expiration` field) can be be restored or recalculated from the audio, playlist and log files.

The [`fsck` command](cli.md) can be used to verify the consistency of the metadata cache.
