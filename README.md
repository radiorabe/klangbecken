# Klangbecken: The RaBe Endless Music Player

[![Build Status](https://travis-ci.org/radiorabe/klangbecken.svg)](https://travis-ci.org/radiorabe/klangbecken)
[![Coverage Status](https://codecov.io/gh/radiorabe/klangbecken/branch/master/graph/badge.svg)](https://codecov.io/gh/radiorabe/klangbecken)

## API

### Dependencies

* Unix-like operating system environment
* **Python** >= 3.6
* **docopt** library for parsing command line arguments
* **Werkzeug** library for the WSGI application
* **PyJWT** library for creating and verify JWT authentication tokens
* **mutagen** library for audio tag editing
* **ffmpeg** binary (>=4.0) for audio analysis

### Development dependencies:

 * tox
 * coverage
 * mock
 * flake8

 ### Setup

Clone the repository:
```bash
git clone git@github.com:radiorabe/klangbecken.git  # FIXME: https
cd klangbecken
```

Create a new virtual Python environment:
```bash
# Python 3.X:
python3 -m venv venv
```

Activate the virtualenv, install the runtime dependencies, and run the development server:
```bash
source venv/bin/activate
pip install -r requirements.txt
python klangbecken serve
```

Now you can access the API:
```bash
curl http://localhost:5000/api/login
```
Additionally install the following development dependencies:
```bash
pip install tox coverage mock flake8
```

#### Run test suite

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


#### Automatically activate and deactivate virtualenvs when changing directories

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


## Contributing

1. Run unittests with your local Python
2. check style
3. Run unittests for all supported Python versions
4. Check coverage
5. Push to your Repo, create pull request, see if continuous integration ran without errors


## Testing environment

### Using Docker

To get a working test environment with Docker, you need one container with Icecast and another with liquidsoap

0. Init Klangbecken data directory
    ```bash
    python klangbecken.py init
    ```

1. Start Klangbecken backend
    ```bash
    python klangbecken.py serve
    ```
2. Start the Icecast container
    ```bash
    sudo docker run --net host moul/icecast
    ```
3. Execute `klangbecken.liq`
    ```bash
    sudo docker run -ti --rm -v $PWD:/var/lib/liquidsoap -e KLANGBECKEN_DATA=data --net host radiorabe/liquidsoap klangbecken.liq
    ```
4. Also have a look at the logs
    ```bash
    sudo docker exec $(sudo docker ps -lq) tail -f /var/log/liquidsoap/klangbecken.log
    ```
5. Now you can open Klangbecken on http://localhost:5000 and the stream on http://localhost:8000

### Authentication

The API does not handle authentication by itself. It is expected that GET or POST requests to `/api/login` are intercepted by an authentication layer, and then forwarded to the app with a valid `REMOTE_USER` parameter in the request environment, in case the authentication was successful. This can for example be achieved by an additional WSGI middleware, or an Apache module like FIXME.

## System Overview
![System overview diagram](doc/system-overview.svg)
