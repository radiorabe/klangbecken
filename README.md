# Klangbecken: The RaBe Endless Music Player

[![Build Status](https://travis-ci.org/radiorabe/klangbecken.svg)](https://travis-ci.org/radiorabe/klangbecken)
[![Coverage Status](https://codecov.io/gh/radiorabe/klangbecken/branch/master/graph/badge.svg)](https://codecov.io/gh/radiorabe/klangbecken)

## API

### Dependencies

* Unix-like operating system environment
* **Python** >= 2.7
* **Werkzeug** library for the WSGI application
* **mutagen** library for audio tag editing
* **ffmpeg** binary for audio analysis

### Development dependencies:

 * virtualenv/venv, setuptools, pip
 * tox
 * coverage
 * mock
 * flake8

## Testing environment

### Using Docker

To get a working test environment with Docker, you need one container with Icecast and another with liquidsoap

1. Start Klangbecken
    ```
    python klangbecken_api.py
    ```
2. Start the Icecast container
    ```
    sudo docker run --net host moul/icecast
    ```
3. Execute `klangbecken.liq`
    ```
    sudo docker run -ti --rm -v $PWD:/var/lib/liquidsoap -e KLANGBECKEN_DATA=data --net host radiorabe/liquidsoap klangbecken.liq
    ```
4. Also have a look at the logs
    ```
    sudo docker exec $(sudo docker ps -lq) tail -f /var/log/liquidsoap/klangbecken.log
    ```
5. Now you can open Klangbecken on http://localhost:5000 and the stream on http://localhost:8000
## System Overview
![System overview diagram](doc/system-overview.svg)
