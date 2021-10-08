# Deployment

This guide broadly describes the necessary steps to deploy a productive Klangbecken instance. It is based on the tools and technologies we use at RaBe, but should be applicable to different but similar tools. We use CentOS (RHEL) 7 as operating system, Apache 2 as web server, FreeIPA for authentication, and Axia ALSA sound drivers.

## Base Installation

On your favourite Linux distribution:
* Install Apache including its development libraries with your package manager.
* Install `git` with your package manager.
* Install Python (at least version 3.7) with development libraries using your package manager or from the [source](https://www.python.org/downloads/).
* Install Liquidsoap from our prebuilt [package](https://github.com/radiorabe/centos-rpm-liquidsoap).

## Prepare Deployment

Befor anything else, deploy your **public SSH key** to the `root` user's `authorized_keys` file.

Create a **virtual environment** for the Python code:
```bash
mkdir /usr/local/venvs
python3.9 -m venv /usr/local/venvs/klangbecken-py39
```

Initialize a bare **git repository** and create checkout and dependencies directories:
```bash
git init --bare /root/klangbecken.git
mkdir /root/klangbecken
mkdir /root/dependencies
```

Install a git **deployment hook**:
```bash
cat > /root/klangbecken.git/hooks/post-receive <<- __EOF_1__
#!/bin/bash

git --work-tree=/root/klangbecken/ --git-dir=/root/klangbecken.git checkout -f
source /usr/local/venvs/klangbecken-py39/bin/activate

echo
echo "##############"
echo "# Installing #"
echo "##############"
pip install --upgrade --no-index --find-links /root/dependencies/ --requirement /root/klangbecken/requirements.txt
pip install --upgrade --no-index --find-links /root/dependencies/ mod_wsgi
rm /root/dependencies/*
pip install --force-reinstall --no-index --no-deps /root/klangbecken

echo
echo "#############"
echo "# Reloading #"
echo "#############"
systemctl reload httpd
if ! cmp --quiet /root/klangbecken/klangbecken.liq /etc/liquidsoap/klangbecken.liq; then
    mv /etc/liquidsoap/klangbecken.liq /etc/liquidsoap/klangbecken.liq.bak
    cp /root/klangbecken/klangbecken.liq /etc/liquidsoap/klangbecken.liq
    echo
    echo "WARNING: Liquidsoap script changed!"
    echo "Run 'systemctl restart liquidsoap@klangbecken' during an off-air moment"
fi
echo
echo "Done!"
__EOF_1__

chmod +x /root/klangbecken.git/hooks/post-receive
```

Initialize the **data directory**:
```bash
source /usr/local/venvs/klangbecken-py39/bin/activate
python -m klangbecken init -d /var/lib/klangbecken
```

Set the **access rights**, such that both apache and liquidsoap users can read and write the data directory:
```bash
groupadd --system klangbecken
usermod -a -G klangbecken apache
usermod -a -G klangbecken liquidsoap

chgrp -R klangbecken /var/lib/klangbecken/
chmod g+s,g+w /var/lib/klangbecken/ /var/lib/klangbecken/*/
setfacl -m "default:group::rw" /var/lib/klangbecken/ /var/lib/klangbecken/*/

# SELinux configuration
semanage fcontext -a -t httpd_sys_rw_content_t "/var/lib/klangbecken.*"
restorecon -vR /var/lib/klangbecken/
```

_On your local machine in your klangbecken git repository_ point a **remote to the production system**:
```bash
git remote add prod root@NAME_OF_YOUR_VM:klangbecken.git
```

**Deploy** the code (including `mod_wsgi`) for the first time to production:
```bash
./deploy.sh
```
_Note:_ To be able to download the `mod_wsgi` package, make sure you have the apache development libraries installed locally.

## Global Configuration

Add a file `/etc/klangbecken.conf` with the global configuration:
```bash
KLANGBECKEN_DATA_DIR=/var/lib/klangbecken
KLANGBECKEN_COMMAND=/usr/local/venvs/klangbecken-py39/bin/klangbecken
KLANGBECKEN_PLAYER_SOCKET=/var/run/liquidsoap/klangbecken.sock
KLANGBECKEN_ALSA_DEVICE=default:CARD=Axia
KLANGBECKEN_EXTERNAL_PLAY_LOGGER=
KLANGBECKEN_API_SECRET=***********************************************
LANG=en_US.UTF-8
```

Replace the `KLANGBECKEN_API_SECRET` with a sufficiently long and random secret key. For example by executing `dd if=/dev/urandom bs=1 count=33 2>/dev/null | base64 -w 0 | rev | cut -b 2- | rev`.

Set the `KLANGBECKEN_ALSA_DEVICE` to your sound card device (`default:CARD=Axia` when you use the Axia ALSA drivers). Optionally specify a `KLANGBECKEN_EXTERNAL_PLAY_LOGGER` command (see [command line interface](cli.md)).

## Liquidsoap

Add an override file for the `liquidsoap@klangbecken` service:
```bash
mkdir /etc/systemd/system/liquidsoap@klangbecken.service.d
cat > /etc/systemd/system/liquidsoap@klangbecken.service.d/overrides.conf <<- __EOF_1__
[Service]
EnvironmentFile=/etc/klangbecken.conf
IOSchedulingClass=best-effort
CPUSchedulingPolicy=rr
IOSchedulingPriority=1
CPUSchedulingPriority=90
__EOF_1__
```

Make sure `/var/run/liquidsoap` exists after booting:
```bash
cat > /etc/tmpfiles.d/liquidsoap.conf <<-__EOF_2__
d /var/run/liquidsoap 0755 liquidsoap liquidsoap - -
__EOF_2__
```

Add liquidsoap user to the `audio` group
```bash
usermod -a -G audio liquidsoap
```

Enable the service:
```bash
systemctl enable liquidsoap@klangbecken.service
```

## Apache

### API with `mod_wsgi`

Add a wsgi file loading the API:
```bash
cat > /var/www/klangbecken_api.wsgi <<-__EOF__
from klangbecken.api import klangbecken_api

with open("/etc/klangbecken.conf") as f:
    config = dict(
        line.rstrip()[len("KLANGBECKEN_") :].split("=", 1)
        for line in f.readlines()
        if line.startswith("KLANGBECKEN_")
    )

application = klangbecken_api(
    config["API_SECRET"], config["DATA_DIR"], config["PLAYER_SOCKET"]
)
__EOF__
```

Configure Apache to use the `mod_wsgi` module:
```bash
cat > /etc/httpd/conf.modules.d/10-wsgi.conf <<-__EOF__
LoadModule wsgi_module /usr/local/venvs/klangbecken-py39/lib/python3.9/site-packages/mod_wsgi/server/mod_wsgi-py39.cpython-39-x86_64-linux-gnu.so
__EOF__
```
Make sure, that the library file (`*.so`) exists at the configured location.

Configure the API in your Apache `VirtualHost` configuration:
```txt
WSGIDaemonProcess klangbecken user=apache group=klangbecken python-home=/usr/local/venvs/klangbecken-py39
WSGIProcessGroup klangbecken
WSGIScriptAlias /api /var/www/klangbecken_api.wsgi

# Forward authorization header to API
RewriteEngine On
RewriteCond %{HTTP:Authorization} ^(.*)
RewriteRule .* - [e=HTTP_AUTHORIZATION:%1]
```

### Authentication

We use `mod_authnz_pam` and `mod_intercept_form_submit` to intercept login requests and authenticate users with PAM.

Configure your Apache `VirtualHost` configuration:
```txt
LoadModule authnz_pam_module modules/mod_authnz_pam.so
LoadModule intercept_form_submit_module modules/mod_intercept_form_submit.so
<Location /api/auth/login>
  <If "%{REQUEST_METHOD} == 'POST'">
    InterceptFormPAMService klangbecken
    InterceptFormLogin login
    InterceptFormPassword password
    InterceptFormClearRemoteUserForSkipped on
    InterceptFormPasswordRedact on
    InterceptFormLoginRealms YOUR_LDAP_REALM ''
  </If>
</Location>
```

_Note:_ If you use LDAP, configure `YOUR_LDAP_REALM` to the correct realm. Otherwise remove the corresponding line.

Allow apache to use PAM (SELinux configuration):
```bash
setsebool -P allow_httpd_mod_auth_pam 1
```

Configure PAM to limit access to users in certain user groups:
```bash
cat > /etc/pam.d/klangbecken <<-__EOF__
auth    required   pam_sss.so
account required   pam_sss.so
account required   pam_access.so accessfile=/etc/klangbecken-http-access.conf
__EOF__

cat > /etc/klangbecken-http-access.conf <<-__EOF__
+ : (staff) : ALL
+ : (admins) : ALL
- : ALL : ALL
__EOF__
```

Check [authentication-middleware.md](authentication-middleware.md) for an alternative to PAM based authentication.

### Data Directory

Configure forwarding requests to `/data` to the data directory in your Apache `VirtualHost` configuration:
```txt
Alias "/data" "/var/lib/klangbecken"
<Directory  /var/lib/klangbecken>
  Require all granted
</Directory>
```

### Front End

Configure redirection rules for the front end in your Apache `VirtualHost` configuration:
```txt
<Directory "/var/www/html">
    <IfModule mod_rewrite.c>
        RewriteEngine On
        RewriteBase /
        RewriteRule ^index\.html$ - [L]
        RewriteCond %{REQUEST_FILENAME} !-f
        RewriteCond %{REQUEST_FILENAME} !-d
        RewriteRule . /index.html [L]
    </IfModule>
</Directory>
```

Fork and clone the front end code from `git@github.com:radiorabe/klangbecken-ui.git` and configure the `PROD_HOST` variable in the deployment script `deploy.sh`.

Run the script to build the project, and copy the files to production:
```bash
./deploy.sh
```

## Systemd Services and Timers

The directory [`doc/systemd`](systemd/) contains example service files for all described services. The files can be copied to `/etc/systemd/system/` on production.

### "On Air" Status Listener (Virtual Sämubox)

Install the Virtual Sämubox binary: https://github.com/radiorabe/virtual-saemubox/releases/latest

Install the [`virtual-saemubox.service`](systemd/virtual-saemubox.service), that sends to current "on air" status to the Liquidsoap player and enable it:
```bash
systemctl enable virtual-saemubox.service
```

### Data Directory Consistency Check

Install the [`klangbecken-fsck.service`](systemd/klangbecken-fsck.service) and [`klangbecken-fsck.timer`](systemd/klangbecken-fsck.timer) files for the `fsck` service, that nightly checks the consistency of the data directory, and enable the timer:
```bash
systemctl enable klangbecken-fsck.timer
```

### Automatically Disable Expired Tracks
Install the [`klangbecken-disable-expired.service`](systemd/klangbecken-disable-expired.service) and [`klangbecken-disable-expired.timer`](systemd/klangbecken-disable-expired.timer) files for the `disable-expired` service, that hourly checks for and disables expired tracks (mostly jingles), and enable the timer:
```bash
systemctl enable klangbecken-disable-expired.timer
```

## Monitoring Checks

The following script checks whether the the Klangbecken had been off air for more than a day. Use it in your monitoring service.

```bash
cat > /usr/local/bin/check_off_air_status <<- __EOF__
#!/bin/env python3.9

import csv
import datetime
import os
import pathlib


if not hasattr(datetime.datetime, "fromisoformat"):
    print("ERROR: datetime.fromisoformat missing")
    print("Install 'fromisoformat' backport package or use a Python version >= 3.7")
    exit(1)

DATA_DIR = os.environ.get("KLANGBECKEN_DATA_DIR", "/var/lib/klangbecken")
path = list((pathlib.Path(DATA_DIR) / "log").glob("*.csv"))[-1]
with open(path) as f:
    reader = csv.DictReader(f)
    entry = list(reader)[-1]

last_play = datetime.datetime.fromisoformat(entry["last_play"])
now = datetime.datetime.now().astimezone()

if now - last_play > datetime.timedelta(days=1):
    print("WARNING: Klangbecken offline for more than one day.")
    print(f"Last track play registered at {last_play}")
    exit(1)
__EOF__

chmod +x /usr/local/bin/check_off_air_status
```
