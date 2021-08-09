# Design

Radio Bern RaBe is an open comunity radio based in Bern, Switzerland.  The station is driven by volunteers, broadcasting more than 80 different shows in more than 20 languages live from our studios.

When no live or pre-programmed radio shows are on air, we broadcast a twentyfour hour music program, the _Klangbecken_. This project implements the software for the _Klangbecken_.


## Requirements

The software has a set of requirements for the listeners, the people doing the music programing, and the IT operations team.

#### Listeners

The listeners desire a stable, gapless, non-repetitious, high-quality music program.

#### Music Programming

Music programmers have to be able to ...

* ... add and remove audio tracks from and to playlists
* ... edit the audio track metadata
* ... have a special playlist for _jingles_ that air four times an hour
* ... control how often each jingle is aired
* ... generate monthly statistics about the aired tracks (mostly jingles)
* ... queue tracks for immediate airing

#### IT Operations

The IT operations team wants ...
 * ... a stable, reliable system
 * ... an independent system that allows maintenance work on other core systems during the time the Klangbecken is on air
 * ... fast disaster recovery
 * ... easy maintainability and future-proofness


## General Goals

Apart from the required features for the listeners and music programmers, we aim for the following goals:

**Self-contained system**: The Klangbecken installation only requires a minimal amount of external services. These are a virtual machine runtime environment, local networking, authentication service, file backup, and monitoring.

**Fast recovery**: All data is stored in regular files. A previous state of the system can be restored by simply restoring the files from backup, or alternatively by manually fixing the human-readable files.

**Automated testing**: All central components of the system are automatically tested by meaningful test cases against multiple versions of our core dependencies (See [actions](https://github.com/radiorabe/klangbecken/actions)).

**Minimal and mature runtime and test dependencies**: To reduce maintenance, we aim for a sensible minimal set of dependencies. We only depend on stable, mature and maintained libraries.


## CLI

The [CLI](../klangbecken/cli.py) provides commands to manage the data directory and run the development serve. For details see the [command line interface documentation](cli.md).


## API

The [APIs](../klangbecken/api.py) are built with [werkzeug](https://FIXME) and a set of [helpers](../klangbecken/api_utils.py). For details about the available endpoints see the [API documentation](api.md).

The APIs are built from handler functions, and accept and return JSON data.  Required data types can be enforced with type annotations.

Example:
```python
from werkzeug.serving import run_simple
from klangbecken.api_utils import API

app = API()

@app.GET("/")
def root(request):
    return "Hello World"

@app.POST("/add")
def add(request, a:int, b:int):
    return {"result": a + b}

run_simple("localhost", 6000, app)
```

Test the API:
```bash
$ curl http://localhost:6000
"Hello World"

$ curl -X POST -H "Content-Type: text/json" --data '{"a": 15, "b": 27}' http://localhost:6000/add
{
  "result": 42
}
```


## Playlist Management

The [playlist code](../klangbecken/api.py) manages the static playlist files in the data directory.

For every playlist there is:
* an `m3u` playlist file
* a directory containing the audio files

The audio files are named with a UUID and a valid file extension. Additionally the code maintains an `index.json` metadata cache, containing all metadata for all files. There is no shared data between the playlists.

Modifications to playlists are done in two steps:
1. The incoming request is analyzed by _analyzer functions_, each generating a list of changes.
2. The gathered list of changes is processed by _processor functions_.

There are three types of changes: `FileAddition`, `MetadataChange` and `FileDeletion`.

_Analyzer functions_ have the following signature, and return a list of change objects:
```python
def analyzer(playlist, fileId, ext, filename):
```
> Where `playlist` is the name of the playlist, `fileId` the UUID of the file, `ext` the file extension and thus the file type, and `filename` the temporary path to the uploaded file.

_Processor functions_ process the generated changes. They validate them or write them to the file system. The functions have the following signature:
```python
def processor(data_dir, playlist, fileId, ext, changes):
```
> Where `data_dir` is the data directory, `playlist` the name of the playlist, `fileId` the UUID of the file, `ext` the extension and file type of the file, and `changes` a list of change objects.


## Player Management

The player [itself](../klangbecken.liq) is written in the [Liquidsoap](https://www.liquidsoap.info/) language.

It reads and monitors the static playlist files, to build it's playlist. The different playlists are then combined as desired. As a safeguard, the player is "always on", and thus serves as a fallback for live and recorded radio shows.

In normal operation the [virtual Sämubox](https://github.com/radiorabe/virtual-saemubox) sends a signal to the Klangbecken to come "on air". The Klangbecken then skips to the next track, to start the program at the beginning of an audio track.

Every played track is logged with using the [play log command](cli.md) at the start of the track.

Liquidsoap provides a telnet interface for querying run-time information and for the modification of dynamic _queue_ playlists.

The [`LiquidsoapClient`](../klangbecken/player.py) encapsulates the liquidsoap telnet interface. Support connecting via TCP with a hostname and port tuple (e.g. `("localhost", 1234)`) or Unix domain sockets (e.g. `./klangbecken.sock`).

It provides a number of methods to interact with the player.

Here is an example session:
```python
>>> from klangbecken.player import LiquidsoapClient
>>> client = LiquidsoapClient()
>>> client.open("klangbecken.sock")
>>> client.info()
{'uptime': '0d 00h 02m 01s', 'liquidsoap_version': 'Liquidsoap 1.4.2', 'api_version': '0.0.13', 'music': '3f712a86-cd57-478f-b3c1-a9a80ceb281f', 'classics': '072f12ef-f4ae-4a9d-ad41-d76f92f6931b', 'jingles': '003ef755-4a82-40b5-b751-d124b85d62a6', 'on_air': {}, 'queue': ''}
>>> client.close()
```

Use the `LiquidsoapClient` as a context manager, to reliably open and close the connection to the player:

```python
with LiquidsoapClient(("localhost", 1234)) as client:
    queue_id = client.push("data/music/072f12ef-f4ae-4a9d-ad41-d76f92f6931b.mp3")
    print(f"Queued track under ID {queue_id}")
```
