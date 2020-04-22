#!/usr/bin/env sh

# abort on errors
set -e

SSH_HOST=root@vm-0016.vm-admin.int.rabe.ch

if git diff --exit-code requirements.txt
then
  TEMP=$(mktemp -d)
  echo "############################"
  echo "# Downloading dependencies #"
  echo "############################"
  pip download --dest "$TEMP" -r requirements.txt
  pip download --dest "$TEMP" mod_wsgi
  echo "##################################"
  echo "# Copying dependencies to server #"
  echo "##################################"
  scp "$TEMP"/* "$SSH_HOST":"dependencies/"
  rm "$TEMP"/*
  rmdir "$TEMP"
  echo "#########################"
  echo "# Deploying application #"
  echo "#########################"
  git push prod
  # make tag
else
  echo Requirements file is dirty
  exit 1
fi
