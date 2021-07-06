import datetime
import functools
import inspect
import json
import sys
import traceback

import jwt
import werkzeug
import werkzeug.routing
from werkzeug.exceptions import Unauthorized, UnprocessableEntity, UnsupportedMediaType
from werkzeug.middleware.dispatcher import DispatcherMiddleware


class API:
    """JSON API.

    >>> app = API()
    >>> @app.GET("/")
    ... def root(request):
    ...     return "Hello World"
    ...
    >>> from werkzeug.test import Client
    >>> client = Client(app)
    >>> body, code, *_ = client.get('/')
    >>> json.loads(b''.join(body))
    'Hello World'

    Now with generic POST data: add a data parameter and optionally specify it's
    type (default is dict)
    >>> @app.POST("/")
    ... def create(request, data:list):
    ...     print(data)
    ...
    >>> body, code, *_ = client.post("/", data="[1, 2, 3]")
    [1, 2, 3]

    >>> body, code, *_ = client.post("/", data="{}")
    >>> code
    '422 UNPROCESSABLE ENTITY'

    And finally requesting a dict in the POST data with specified fields (and types)

    >>> @app.PUT("/")
    ... def update(request, name, age:int, superhuman:bool=False):
    ...     print(f"{name} is {age} years old.")
    ...     print(f"{name} is {'' if superhuman else 'not '}superhuman.")
    ...
    >>> import json
    >>> data = {"name": "Betsy", "age": 34}
    >>> body, code, *_ = client.put("/", data=json.dumps(data))
    Betsy is 34 years old.
    Betsy is not superhuman.
    >>> code
    '200 OK'

    >>> data = {"name": "Betsy"}
    >>> body, code, *_ = client.put("/", data=json.dumps(data))
    >>> code
    '422 UNPROCESSABLE ENTITY'

    >>> data = {"name": "Betsy", "age": "34"}
    >>> body, code, *_ = client.put("/", data=json.dumps(data))
    >>> code
    '422 UNPROCESSABLE ENTITY'

    >>> data = {"name": "Betsy", "age": 34, "superhuman": True}
    >>> body, code, *_ = client.put("/", data=json.dumps(data))
    Betsy is 34 years old.
    Betsy is superhuman.
    >>> code
    '200 OK'

    >>> data = {"name": "Betsy", "age": 34, "verysmart": True}
    >>> body, code, *_ = client.put("/", data=json.dumps(data))
    >>> code
    '422 UNPROCESSABLE ENTITY'

    >>> data = "This is not valid JSON"
    >>> body, code, *_ = client.put("/", data=data)
    >>> code
    '415 UNSUPPORTED MEDIA TYPE'
    """

    def __init__(self):
        self._url_map = werkzeug.routing.Map()

    def route(self, string, methods=("GET",), func=None):
        """Register a route with a callback.

        This function can be used either directly:

        >>> api = API()
        >>> api.route("/", func=lambda request: "Hello!")  # doctest: +ELLIPSIS
        <function <lambda> at 0x...>

        or as a decorator
        >>> @api.route("/user/<id>")
        ... def home(request, id):
        ...     return f"Welcome home {id}!"
        ...

        To test it use the Client class.
        >>> from werkzeug.test import Client
        >>> client = Client(api)
        >>> client.get("/")       # doctest: +ELLIPSIS
        (<werkzeug.wsgi.ClosingIterator ...>, '200 OK', Headers(...))
        >>> json.loads(b"".join(_[0]))
        'Hello!'
        >>> client.get("/user/007")       # doctest: +ELLIPSIS
        (<werkzeug.wsgi.ClosingIterator ...>, '200 OK', Headers(...))
        >>> json.loads(b"".join(_[0]))
        'Welcome home 007!'
        """
        if func is None:
            return functools.partial(self.route, string, methods)

        rule = werkzeug.routing.Rule(string, methods=methods)
        werkzeug.routing.Map([rule])  # Bind rule temporarily
        url_params = rule.arguments

        sig = inspect.signature(func)
        params = sig.parameters
        param_keys = list(sig.parameters.keys())

        # The first argument is the request, after that, the route parameters follow
        # The order of the parameters is ignored
        func_url_params = set(param_keys[1 : len(url_params) + 1])
        missmatch = url_params ^ func_url_params
        if missmatch:
            raise TypeError(
                f"{func.__name__}() arguments and route parameter missmatch "
                f"({func_url_params} != {url_params})"
            )

        body_params = param_keys[len(url_params) + 1 :]
        body_type = None
        if len(body_params) == 1 and body_params[0] == "data":
            body_type = (
                params["data"].annotation
                if params["data"].annotation is not inspect.Parameter.empty
                else dict
            )
            content_types = {}
        elif body_params:
            body_type = dict
            content_types = {
                key: params[key].annotation
                for key in body_params
                if params[key].annotation is not inspect.Parameter.empty
            }

        if body_type:
            func = _parse_json_body_wrapper(func, body_type, content_types)

        self._url_map.add(werkzeug.routing.Rule(string, methods=methods, endpoint=func))
        return func

    def GET(self, string):
        """Shorthand for registering GET requests.

        Use as a decorator:
        >>> api = API()
        >>> @api.GET("/admin")
        ... def admin_home(request):
        ...     return "Nothing here"
        ...
        >>> from werkzeug.test import Client
        >>> client = Client(api)
        >>> client.get("/admin")   # doctest: +ELLIPSIS
        (<werkzeug.wsgi.ClosingIterator ...>, '200 OK', Headers(...))
        """
        return self.route(string, ("GET",))

    def POST(self, string):
        """Shorthand for registering POST requests."""
        return self.route(string, ("POST",))

    def PUT(self, string):
        """Shorthand for registering PUT requests."""
        return self.route(string, ("PUT",))

    def PATCH(self, string):
        """Shorthand for registering PATCH requests."""
        return self.route(string, ("PATCH",))

    def DELETE(self, string):
        """Shorthand for registering DELETE requests."""
        return self.route(string, ("DELETE",))

    def __call__(self, environ, start_response):
        try:
            request = werkzeug.Request(environ)
            adapter = self._url_map.bind_to_environ(environ)
            endpoint, values = adapter.match()

            # Dispatch request
            response = endpoint(request, **values)
            response = _json_response(response)
        except werkzeug.exceptions.HTTPException as e:
            response = _json_response(
                {"code": e.code, "name": e.name, "description": e.description},
                status=e.code,
            )
        except Exception as e:
            response = _json_response(
                {"code": 500, "name": "Internal Server Error"}, status=500
            )
            print(f"ERROR {e.__class__.__name__}: {str(e)}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
        return response(environ, start_response)


def _json_response(data, status=200):
    if data is None:
        return werkzeug.Response(status=status)
    else:
        data = json.dumps(data, indent=2) + "\n"
        return werkzeug.Response(data, status=status, mimetype="application/json")


def _parse_json_body_wrapper(func, body_type, content_types):  # noqa: C901
    sig = inspect.signature(func)

    @functools.wraps(func)
    def wrapper(request, *args, **kwargs):
        try:
            data = str(request.data, "utf-8").strip()
        except UnicodeDecodeError:
            raise UnsupportedMediaType("Cannot parse request body: invalid UTF-8 data")

        if not data:
            raise UnsupportedMediaType("Cannot parse request body: no data supplied")

        try:
            data = json.loads(data)
        except json.decoder.JSONDecodeError:
            raise UnsupportedMediaType("Cannot parse request body: invalid JSON")

        if not isinstance(data, body_type):
            raise UnprocessableEntity(
                f"Invalid data format: {body_type.__name__} expected"
            )

        if body_type == dict and content_types:
            too_many = data.keys() - sig.parameters.keys()
            if too_many:
                raise UnprocessableEntity(f"Key not allowed: {', '.join(too_many)}")

            kwargs.update(data)
            bound = sig.bind_partial(request, *args, **kwargs)
            bound.apply_defaults()

            missing = sig.parameters.keys() - bound.arguments.keys()
            if missing:
                raise UnprocessableEntity(f"Key missing: {', '.join(missing)}")

            for key, data_type in content_types.items():
                if not isinstance(bound.arguments[key], data_type):
                    raise UnprocessableEntity(
                        f"Invalid format: '{key}' must be of type {data_type.__name__}."
                    )
        else:
            kwargs["data"] = data

        return func(request, *args, **kwargs)

    return wrapper


class BaseJWTAuthMiddleware:
    """Middleware authorizing access to chained application using JWT.

    Attention: Authentication must be provided.

    This middleware exposes two endpoints:
     - /auth/login/ for generation new tokens.
     - /auth/renew/ for renewing an existing token

    Tokens are short-lived and are valid for only 15 minutes, but expired tokens
    can be renewed during one week starting from their initial issueing date.
    """

    def __init__(
        self,
        app,
        secret,
        exempt=[],
        *,
        prefix="/auth",
        login_methods=("POST",),
    ):

        auth_api = API()
        auth_api.route(
            "/login/", methods=login_methods, func=functools.partial(self._login)
        )
        auth_api.route(
            "/renew/", methods=("POST",), func=functools.partial(self._renew)
        )

        self.app = DispatcherMiddleware(app, {prefix: auth_api})

        self.exempt = (
            exempt
            + [(method, prefix + "/login/") for method in login_methods]
            + [("POST", prefix + "/renew/")]
        )

        self.secret = secret

    def __call__(self, environ, start_response):
        request_line = (environ["REQUEST_METHOD"], environ["PATH_INFO"])
        if any(request_line == (method, path) for method, path, *_ in self.exempt):
            # Requests exempted from auth checking are forwarded directly
            response = self.app
        else:
            # All others: Check authorization and then forward to app
            request = werkzeug.Request(environ)
            try:
                user = self._check_authorization(request)
                environ["REMOTE_USER"] = user
                response = self.app
            except Unauthorized as e:
                response = _json_response(
                    {"code": e.code, "name": e.name, "description": e.description},
                    status=e.code,
                )

        return response(environ, start_response)

    def _check_authorization(self, request):
        """Raise Exception (Unauthorized) when authorization failed."""

        if "Authorization" not in request.headers:
            raise Unauthorized("No authorization header supplied")

        auth = request.headers["Authorization"]
        if not auth.startswith("Bearer "):
            raise Unauthorized("Invalid authorization header")

        token = auth[len("Bearer ") :]
        try:
            contents = jwt.decode(
                token,
                self.secret,
                algorithms=["HS256"],
                options={"require_exp": True, "require_iat": True},
            )
            return contents["user"]
        except jwt.ExpiredSignatureError:
            raise Unauthorized("Expired token")
        except (jwt.InvalidTokenError, KeyError):
            raise Unauthorized("Invalid token")

    def _login(self, request):
        user = self.authenticate(request)
        now = datetime.datetime.utcnow()
        claims = {"user": user, "iat": now, "exp": now + datetime.timedelta(minutes=15)}
        token = jwt.encode(claims, self.secret, algorithm="HS256")

        return {"token": token}

    def _renew(self, request, token: str):
        now = datetime.datetime.utcnow()
        try:
            # Valid tokens can always be renewed withing their short lifetime,
            # independent of the issuing date
            claims = jwt.decode(
                token,
                self.secret,
                algorithms=["HS256"],
                options={"require_exp": True, "require_iat": True},
            )
        except jwt.ExpiredSignatureError:
            # Expired tokens can be renewed for at most one week after the
            # first issuing date
            claims = jwt.decode(
                token,
                self.secret,
                algorithms=["HS256"],
                options={
                    "require_exp": True,
                    "require_iat": True,
                    "verify_exp": False,
                },
            )
            issued_at = datetime.datetime.utcfromtimestamp(claims["iat"])
            if issued_at + datetime.timedelta(days=7) < now:
                raise Unauthorized("Unrenewable expired token")
        except jwt.InvalidTokenError:
            raise Unauthorized("Invalid token")

        claims["exp"] = now + datetime.timedelta(minutes=15)

        token = jwt.encode(claims, self.secret, algorithm="HS256")

        return {"token": token}

    def authenticate(self, request):
        """Authenticate user.

        Returns a user identification if authentication passed.
        Raises Unauthorized otherwise.  This method must be overwritten
        in an implementation class.
        """
        raise Unauthorized()  # pragma: no cover


class ExternalAuth(BaseJWTAuthMiddleware):
    def __init__(self, *args, login_methods=("GET", "POST"), **kwargs):
        super().__init__(*args, login_methods=login_methods, **kwargs)

    def authenticate(self, request):
        if request.remote_user is None:
            raise Unauthorized()

        return request.remote_user


class DummyAuth(BaseJWTAuthMiddleware):
    """Dummy Authenticator.

    Create an API:
    >>> api = API()
    >>> @api.GET("/")
    ... def root(request):
    ...     return "Hello World"
    ...

    Wrap it with an authentication/authorization layer:
    >>> app = DummyAuth(api, "not a secret")

    >>> from werkzeug.test import Client
    >>> client = Client(app)

    By default, access is denied:
    >>> client.get("/")       # doctest: +ELLIPSIS
    (<werkzeug.wsgi.ClosingIterator ...>, '401 UNAUTHORIZED', Headers(...))

    Login to get a token:
    >>> body, code, *_ = client.post("/auth/login/")
    >>> code
    '200 OK'
    >>> token = json.loads(b"".join(body))["token"]
    >>> token                                                      # doctest: +ELLIPSIS
    'eyJ...'

    Use the token to gain access:
    >>> headers = {"Authorization": f"Bearer {token}"}
    >>> client.get("/", headers=headers)                           # doctest: +ELLIPSIS
    (<werkzeug.wsgi.ClosingIterator ...>, '200 OK', Headers(...))
    """

    def authenticate(self, request):
        return "dummyuser"
