# Klangbecken: The RaBe Endless Music Player

[![Build Status](https://travis-ci.org/radiorabe/klangbecken.svg?branch=master)](https://travis-ci.org/radiorabe/klangbecken)
[![Coverage Status](https://codecov.io/gh/radiorabe/klangbecken/branch/master/graph/badge.svg)](https://codecov.io/gh/radiorabe/klangbecken)

## Description
This repo contains two parts of the RaBe-Klangbecken infrastructure:
* The API (`klangbecken.py`).
* The script for the playout (`klangbecken.liq`).

Some additional parts are in their own repository:
* The listener for the current status, the [virtual Sämubox](https://github.com/radiorabe/virtual-saemubox).
* The [UI](https://github.com/radiorabe/klangbecken-ui).

How they interact can be seen in the [system overview diagram](doc/system-overview.svg):

![System overview diagram](doc/system-overview.svg)

### System requirements
* Unix-like operating system environment
* **Python** >= 3.6
  * **docopt** library for parsing command line arguments
  * **Werkzeug** library for the WSGI application
  * **PyJWT** library for creating and verify JWT authentication tokens
  * **mutagen** library for audio tag editing
  * **ffmpeg** binary (>=4.0) for audio analysis
  * Development dependencies: **tox**, **coverage**, **mock**, **flake**
* **Liquidsoap** for sending the audio

## Setup

### Clone the repository:
```bash
git clone https://github.com:radiorabe/klangbecken.git
cd klangbecken
```

### Create `python` virtual environment (optional)
```bash
mkvirtualenv klangbecken
# or
python3 -m venv venv && source venv/bin/activate
```

### Install dependencies:
* Python
  ```bash
  pip install -r requirements.txt
  ```
* Liquidsoap (on CentOS 7 you can also use our prebuilt [package](https://github.com/radiorabe/centos-rpm-liquidsoap))
  ```bash
  opam init
  opam switch create klangbecken 4.07.0 # we need liquidsoap 1.3.7 which does not run after OCaml 4.07.0
  opam depext alsa mad lame vorbis taglib liquidsoap.1.3.7
  opam install alsa mad lame vorbis taglib liquidsoap.1.3.7
  ```

### Run the programs
* `klangbecken.py`
  ```bash
  python3 klangbecken.py serve
  ```
* `klangbecken.liq`
  ```bash
  export KLANGBECKEN_ALSA_DEVICE="default"
  export KLANGBECKEN_DATA="data"
  export KLANGBECKEN_PATH="./klangbecken.py"
  export KLANGBECKEN_SOCKET_PATH="/tmp/klangbecken.liq.sock"
  liquidsoap klangbecken.liq
  ```
* If you want to set the onair status manually you can connect to the socket using `netcat`
  ```bash
  echo "klangbecken.onair True" | nc -U -w 1 /tmp/klangbecken.liq.sock
  ```

## Notes

### Authentication

The API does not handle authentication by itself. It is expected that GET or POST requests to `/api/login` are intercepted by an authentication layer, and then forwarded to the app with a valid `REMOTE_USER` parameter in the request environment, in case the authentication was successful. This can for example be achieved by an additional WSGI middleware, or an Apache module like FIXME.


### Run test suite

Run tox to run all unit test for multiple Python versions and make a code style check in the end. Make sure, that you have at least Python 2.7 and one supported Python 3 version installed locally.
```bash
tox
```

For the impatient, use parallel execution
```bash
tox -p auto
```

#### Run test suite only once

```bash
python -m unittest discover
```

#### Check your style
```bash
flake8
```


### Automatically activate and deactivate virtualenvs when changing directories

Add the following to your `~/.bashrc` to automatically activate the virtualenv when cd-ing into a directory containing a `venv` directory, and deactivating it, when leaving.

```bash
_update_path() {
  # Activate python virtualenv if 'venv' directory exists somewhere
  P=$(pwd)
  while [[ "$P" != / ]]; do
      if [[ -d "$P/venv" && -f "$P/venv/bin/activate" ]]; then
          if [[ "$P/venv" != "$VIRTUAL_ENV" ]]; then
              source $P/venv/bin/activate
          fi
          FOUND_VENV=yes
          break
      fi
      P=$(dirname "$P")
  done
  if [[ "$FOUND_VENV" != yes && -v VIRTUAL_ENV ]]; then
      deactivate
  fi

  unset FOUND_VENV
  unset P
  true
}

cd() {
  builtin cd "$@"
  _update_path
}

_update_path
```


### Contributing

1. Run unittests with your local Python
2. check style
3. Run unittests for all supported Python versions
4. Check coverage
5. Push to your Repo, create pull request, see if continuous integration ran without errors
