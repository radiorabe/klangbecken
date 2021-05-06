#!/usr/bin/env bash

# abort on errors
set -e

# "parse" command line arguments
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

echo "##################"
echo "# Perform checks #"
echo "##################"

# are there prod and upstream remotes?
if ! git remote | grep --quiet "^prod$"; then
    echo "ERROR: No 'prod' remote configured"
    exit 1
fi
if ! git remote | grep --quiet "^upstream$"; then
    echo "ERROR: No 'upstream' remote configured"
    exit 1
fi

PROD_HOST=$(git remote get-url prod | cut -d: -f1)

# are we clean?
if ! git diff --exit-code --quiet; then
    echo "ERROR: Working directory is NOT clean."
    exit 1
fi

# are we on the master branch?
if [ "$(git branch --show-current)" != "master" ]
then
    echo "ERROR: We are NOT on the 'master' branch."
    exit 1
fi

# fetch latest version from upstream
if ! git fetch upstream master; then
    echo
    echo "ERROR: cannot fetch current upstream version."
    exit 1
fi

# are we pointing at upstream/master?
if ! git show --no-patch --pretty=format:%D | grep --quiet upstream/master
then
    echo "ERROR: 'master' branch is NOT pointing at 'upstream/master'."
    echo "       Make sure, your local version is in sync with upstream."
    exit 1
fi

# check connection to prod and fetch state
if ! git fetch prod master; then
    echo "ERROR: cannot connect to prod to fetch current version."
    exit 1
fi

# is prod/master already up to date?
if git show --no-patch --pretty=format:%D | grep --quiet prod/master
then
    echo
    echo "ERROR: 'prod' is already up to date."
    exit 1
fi

# check current version
INIT_VERSION=$(sed -n -e 's/^__version__\s*=\s*"\(.*\)"\s*$/\1/p' klangbecken/__init__.py )
SETUP_VERSION=$(sed -n -e 's/^\s*version\s*=\s*"\(.*\)".*$/\1/p' setup.py)

if [ "$INIT_VERSION" != "$SETUP_VERSION" ]
then
    echo "ERROR: Version numbers in 'setup.py' and 'klangbecken/__init__.py' do not match."
    exit 1
fi

TAG_VERSION=$(git tag --merged HEAD -l "v*" | sort -V | tail -n 1)
if [ "v$SETUP_VERSION" != "$TAG_VERSION" ]
then
    echo "ERROR: Tag and package versions do not match."
    exit 1
fi

echo
echo -n "Everything looks good. Start deployment? [Y/n]"
read -n 1 ANS

if ! [ -z "$ANS" -o "$ANS" = "y" -o "$ANS" = "Y" ]; then
    echo "    Bye ..."
    exit 1
fi

echo
echo "#####################"
echo "# Increment version #"
echo "#####################"
OLD_VERSION=$SETUP_VERSION
LAST_DIGIT=$(echo "$OLD_VERSION" | cut -d. -f3)
LAST_DIGIT=$((LAST_DIGIT + 1))
NEW_VERSION=$(echo "$OLD_VERSION" | cut -d. -f1-2)."$LAST_DIGIT"

sed -i "s/__version__ = \"$OLD_VERSION\"/__version__ = \"$NEW_VERSION\"/" klangbecken/__init__.py
sed -i "s/version=\"$OLD_VERSION\",/version=\"$NEW_VERSION\",/" setup.py

git add klangbecken/__init__.py setup.py
git commit -m "Version bump v$NEW_VERSION"

TEMP=$(mktemp -d)
echo
echo "#########################"
echo "# Download dependencies #"
echo "#########################"
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
echo "###############################"
echo "# Copy dependencies to server #"
echo "###############################"
scp "$TEMP"/* "$PROD_HOST":"dependencies/"
rm "$TEMP"/*
rmdir "$TEMP"

echo
echo "######################"
echo "# Deploy application #"
echo "######################"
git push prod master

echo
echo "#######################"
echo "# Finalize deployment #"
echo "#######################"
git tag "v$NEW_VERSION"
git push upstream --tags

echo
echo "Deployment successful!"
