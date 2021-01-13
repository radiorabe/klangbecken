# Additional Tools

## Working with Python's virtual environments

### virtualenvwrapper

The `virtualenvwrapper` package supports managing many virtual environments. See their [documentation page](https://virtualenvwrapper.readthedocs.io/en/latest/index.html)  for more information.

### Standard library `venv` package

Since Python 3.3 the standard library contains the `venv` package supporting the creation of virtual environments.  We recommend to create the virtual environment in the root directory of your project and naming it either `.venv` or `venv` (see [The Hichhiker's Guide to Python](https://docs.python-guide.org/dev/virtualenvs/#basic-usage)).

Creating a virtual environment:
```bash
python -m venv .venv
```

Activate the virtual environment:
```bash
source .venv/bin/activate
```

Deactivate the virtual environment:
```bash
deactivate
```

### Automatically activate and deactivate virtual environments

The following helper automatically activates a virtual environment when `cd`-ing into a directory with a accompanying virtual environment.  For this to work, the virtual environment must be located in the root directory of your project and be named `.venv` or `venv`.  Activation also works whe `cd`-ing into a subdirectory.  Changing into a directory outside of your project's directory structure will automatically deactivate the virtual environment.

Add the following lines to your `~/.bashrc`:
```bash
_update_path() {
  # Activate python virtualenv if '.venv' or 'venv' directory exists
  P=$(pwd)
  while [[ "$P" != / ]]; do
      if [[ -d "$P/.venv" && -f "$P/.venv/bin/activate" ]]; then
          if [[ "$P/.venv" != "$VIRTUAL_ENV" ]]; then
              source $P/.venv/bin/activate
          fi
          FOUND_VENV=yes
          break
      fi
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

## Automatic code formatting

#### Automate formatting using pre-commit

After registering hooks with `install` pre-commit will abort commits if there are black, isort or flake8 changes to be made. If machine fixable (ie. black and isort) pre-commit usually applies those changes leaving you to stage them using `git add` before retrying your commit.


```bash
pip install pre-commit
pre-commit install
```

Store the following configuration in `.pre-commit-config.yaml`:
```yaml
repos:
  - repo: local
    hooks:
      - id: black
        name: black
        language: system
        entry: black
        types: [python]
      - id: isort
        name: isort
        language: system
        entry: isort -y
        types: [python]
      - id: flake8
        name: flake8
        language: system
        entry: flake8
        types: [python]
```

You can also run black, isort and flake8 on all content without comitting:
```bash
pre-commit run -a
```
