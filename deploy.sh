#!/usr/bin/env sh

# abort on errors
set -e

SSH_HOST=root@vm-0016.vm-admin.int.rabe.ch

if [ $# -eq 0 ]; then
  MOD_WSGI=yes
elif [ $# -eq 1 ] && [ "$1" = "--no-mod-wsgi" -o "$1" = "-n" ]; then
  MOD_WSGI=no
else
  echo "Klangbecken deployment script"
  echo "Usage:./deploy [-n]"
  echo ""
  echo "Options:"
  echo "  -n, --no-mod-wsgi    Do not download and install mod_wsgi"
  echo ""
  echo "Note: Downloading mod_wsgi requires httpd-devel libraries"
  echo "      to be installed locally"
  exit 1
fi

if git diff --exit-code requirements.txt
then
  TEMP=$(mktemp -d)
  echo "############################"
  echo "# Downloading dependencies #"
  echo "############################"
  pip download --dest "$TEMP" --no-binary :all: -r requirements.txt
  if [ "$MOD_WSGI" = "yes" ]; then
    if ! pip download --dest "$TEMP" --no-binary :all: mod_wsgi; then
        echo
        echo "Note: Downloading mod_wsgi requires httpd-devel libraries"
        echo "      to be installed locally"
        exit 1
    fi
  fi
  echo
  echo "##################################"
  echo "# Copying dependencies to server #"
  echo "##################################"
  scp "$TEMP"/* "$SSH_HOST":"dependencies/"
  rm "$TEMP"/*
  rmdir "$TEMP"
  echo
  echo "#########################"
  echo "# Deploying application #"
  echo "#########################"
  git push prod
else
  echo "WARNING: Requirements file is dirty"
  exit 1
fi
