# API

## Authentication

The API uses JSON web tokens (JWT) for authentication.  The underlying authentication must be provided, by intercepting calls to `/api/auth/login`. The API does not specify a specific authentication method, like password-based or Kerberos, but expects to receive a valid `REMOTE_USER` string upon a successful authentication.

Tokens are valid for 15 minutes. Valid tokens can be renewed indefinitely, and expired tokens can be renewed during one week after first issueing.

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
`/<PLAYLIST>/`| `POST`| Create new entry to playlist, by uploading an audio file. Returns all parsed and generated metadata.
`/<PLAYLIST>/<UUID>.<EXT>`|  `PUT`|  Update playlist entry metadata. Allowed keys are `artist`, `title`, `album` and `weight`.
`/<PLAYLIST>/<UUID>.<EXT>`| `DELETE` | Delete playlist entry.

Endpoint example: `/api/playlist/jingles/9967f00b-883a-4aa0-98e7-5085cdc380d3.mp3`

## Static Data

`/data` provides read-only access to all static playlist and log files. The metadata cache `index.json` speeds up client operation, by removing the need to perform client-side audio file metadata parsing.

Base: `/data`

Endpoint | Description | Example
---------|-------------|---------
`/index.json` | Metadata cache | `/data/index.json`
`/<PLAYLIST>.m3u` | Playlist files | `/data/music.m3u`
`/<PLAYLIST>/<UUID>.<EXT>`| Audio files | `/data/jingles/9967f00b-883a-4aa0-98e7-5085cdc380d3.mp3`
`/log/<YEAR>-<MONTH>.csv`| Monthly play log | `/data/log/2020-8.csv`
