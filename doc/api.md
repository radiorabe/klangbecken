# API

## Authorization and Authentication

The API uses JSON web tokens (JWT) for authorizing access to non read-only endpoints.  The underlying authentication method must be provided by intercepting `POST` requests to `/api/auth/login/`. The API does not specify a specific authentication method, like password-based or Kerberos, but expects to receive a valid `REMOTE_USER` string upon a successful authentication.

Tokens are valid for 15 minutes. Valid tokens can be renewed indefinitely. Expired tokens can be renewed up to one week after first issuing them.

Base: `/api/auth`

Endpoint | Method(s) | Description
---------|-----------|------------
`/login`| `GET`, `POST`| Login and return an newly created token.
`/renew`| `POST`| Renew existing Token.

Endpoint example: `/api/auth/renew`

## Playlist

The playlist API allows editing static playlist entries.  The allowed playlists and file formats are configured in [`klangbecken/settings.py`](../klangbecken/../klangbecken/settings.py).

Base: `/api/playlist`

Endpoint | Method | Description
---------|--------|------------
`/<PLAYLIST>/`| `POST`| Create new entry to a playlist by uploading an audio file. Returns all extracted and generated metadata.
`/<PLAYLIST>/<UUID>.<EXT>`|  `PUT`|  Update playlist entry metadata. Allowed keys are `artist`, `title`, `weight`, and `expiration`.
`/<PLAYLIST>/<UUID>.<EXT>`| `DELETE` | Delete playlist entry.

Endpoint example: `/api/playlist/jingles/9967f00b-883a-4aa0-98e7-5085cdc380d3.mp3`

Data types for playlist entry metadata updates:
* **artist**: `string`
* **title**: `string`
* **weight**: `int` (>= 0)
* **expiration**: empty or ISO8601 datetime `string`

_Note for datetime strings_: The string _must_ specify a date _and_ a time including hours, minutes and seconds (fractions of a second are optional) separated by the letter `T`. Timezone information _must_ be provided, either as (+/-) offset from UTC or by the letter `Z` for UTC datetime strings. In JS `Date` objects are automatically converted to compatible UTC datetime strings by `JSON.stringify` using `Date.prototype.toJSON()`.

## Player

The player API allows getting information about the running audio player and edit a "play next" queue.

Base: `/api/player`

Endpoint | Method | Description
---------|--------|------------
`/`| `GET`| Get player information.
`/reload/<PLAYLIST>`| `POST`| Force player to reload a playlist (usually after modifications).
`/queue/` | `GET` | List queue entries.
`/queue/` | `POST` | Add audio track to queue. Requires a `filename` argument (string in the format `<PLAYLIST>/<UUID>.<EXT>`) and returns the assigned `queue_id`.
`/queue/<QUEUE_ID>` | `DELETE` | Delete queue entry.


Endpoint example: `/api/player/queue/15`

## Static Data

`/data` provides read-only access to the data directory containing the audio, playlist and log files. The metadata cache `index.json` speeds up client operation, by removing the need to perform client-side audio file metadata parsing.

Base: `/data`

Endpoint | Description | Example
---------|-------------|---------
`/index.json` | Metadata cache |
`/<PLAYLIST>.m3u` | Playlist files | `/data/music.m3u`
`/<PLAYLIST>/<UUID>.<EXT>`| Audio files | `/data/jingles/9967f00b-883a-4aa0-98e7-5085cdc380d3.mp3`
`/log/<YEAR>-<MONTH>.csv`| Monthly play log | `/data/log/2020-08.csv`
`/log/fsck.log`| Nightly `fsck` run output |
