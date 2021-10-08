# Authentication Middleware

As an alternative to using PAM for authentication you can write your own wsgi middleware.

Here is some minimalistic sample code:
```python
from werkzeug.security import check_password_hash
from werkzeug.wrappers import Request

class PasswordFileAuthenticationMiddleware:
    def __init__(self, app, password_file):
        self.app = app
        self.password_file = password_file

    def __call__(self, environ, start_response):
        if environ["REQUEST_METHOD"] == "POST" and environ["PATH_INFO"] == "/auth/login/":
            request = Request(environ)
            username = request.form["login"]
            password = request.form["password"]
            with open(self.password_file) as f:
                passwords = dict(line.rstrip().split(":", maxsplit=1) for line in f)
            if username not in passwords:
                raise Unauthorized()
            if not check_password_hash(passwords[username], password):
                raise Unauthorized()
            environ["REMOTE_USER"] = username
        return self.app(environ, start_response)
```

To use it wrap the API `application` in your middleware at the very end of your wsgi file:
```python
...
application = PasswordFileAuthenticationMiddleware(application, "/path/to/pwfile")
```

To generate password hashes use `werkzeug`'s helper function:
```python
>>> from werkzeug.security import generate_password_hash
>>> pwhash = generate_password_hash("love")
>>> pwhash
'pbkdf2:sha256:260000$MMNfmCYMFGGVMBuL$d4d48bb539d111f42111e657d32346a203064255d3f36e0cc353b3f22ceddb20'
>>> with open("/path/to/pwfile", "a") as f:
...    print("john_doe", "pwhash", sep=":", file=f)
```
