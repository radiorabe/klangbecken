#!/usr/bin/env sh

# abort on errors
set -e

SSH_HOST=$(git remote get-url prod | cut -d: -f1)

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

if ! git diff --exit-code requirements.txt
then
  echo "ERROR: Requirements file is dirty"
  exit 1
fi

if ! git diff --exit-code setup.py
then
  echo "ERROR: `setup.py` is dirty"
  exit 1
fi

if [ "$(git branch --show-current)" != "master" ]
then
    echo "ERROR: We are not on the 'master' branch."
    exit 1
fi

INIT_VERSION=$(sed -n -e 's/^__version__\s*=\s*"\(.*\)"\s*/\1/p' klangbecken/__init__.py )
SETUP_VERSION=$(sed -n -e 's/^\s*version\s*=\s*"\(.*\)".*$/\1/p' setup.py)

if [ "$INIT_VERSION" != "$SETUP_VERSION" ]
then
    echo "ERROR: Version numbers in 'setup.py' and 'klangbecken/__init__.py' do not match."
    exit 1
fi
VERSION="v$INIT_VERSION"

TAG_VERSION=$(git tag -l "v*" | sort -V | tail -n 1)
if [ "$VERSION" = "$TAG_VERSION" ]
then
    echo "ERROR: Version has not been incremented: $VERSION < $TAG_VERSION"
    exit 1
fi

if [ "$((echo $VERSION; echo $TAG_VERSION) | sort -V | tail -n 1)" = "$TAG_VERSION" ]
then
    echo "ERROR: New version number is smaller than old one."
    exit 1
fi


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
git push prod master

git tag $VERSION

echo
echo "Deployment successful!"
echo "Push the newly created version tag to the upstream repository with"
echo "    `git push --tags upstream master`"
