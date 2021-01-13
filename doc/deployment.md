# Deployment

CentOS/RHEL 7 but applicable to other Linux distributions..


## Base Installation

Python
Apache
Liquidsoap

Where to get: radio rabe

## Prepare Data Directory

### SELinux


## Axia alsa driver

## Liquidsoap
Overrrides

Env variables


## Python virtualenv

pip install
or pip download, scp and pip install --no-index

## mod_wsgi

## wsgi file

## Apache

For authentication see ...

- Rewrites for frontend

## onair listener


### Python 3.6 install log

yum install -y python36 python36-devel

create python3.6 venv
point to this env in httpd klangbecken conf (wsgi python home)

pip install mod_wsgi

point /etc/httpd/modules.conf.d/10-wsgi.conf module string to module.

LoadModule wsgi_module /usr/local/venvs/klangbecken-py36/lib/python3.6/site-packages/mod_wsgi/server/mod_wsgi-py36.cpython-36m-x86_64-linux-gnu.so
