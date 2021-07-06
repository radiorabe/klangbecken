import datetime
import doctest
import json
import unittest
from unittest import mock

from werkzeug.test import Client

from .utils import capture


# most testing is done in  doctests
def load_tests(loader, tests, ignore):
    import klangbecken.api_utils

    # load doctests
    tests.addTests(doctest.DocTestSuite(klangbecken.api_utils))
    return tests


class AdditionalTestCase(unittest.TestCase):
    def setUp(self):
        from klangbecken.api_utils import API

        app = API()

        @app.PATCH("/")
        def root(request):
            int("1.5")

        self.client = Client(app)

    def testError500(self):
        with capture(self.client.patch, "/") as (out, err, resp):
            pass
        self.assertEqual(resp.status_code, 500)
        self.assertIn("ValueError: invalid literal for int() with base 10: '1.5'", err)

    def testParameterMismatch(self):
        from klangbecken.api_utils import API

        app = API()
        with self.assertRaises(TypeError):

            @app.POST("/<id>")
            def dummy(request, number):
                pass


class TokenRenewalTestCase(unittest.TestCase):
    def setUp(self):
        from klangbecken.api_utils import API, DummyAuth

        api = API()

        @api.GET("/")
        def root(request):
            return "Hello World"

        app = DummyAuth(api, "no secret")
        self.client = Client(app)

    def testImmediateRenewal(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 401)
        self.assertIn(b"No authorization header supplied", resp.data)

        resp = self.client.post("/auth/login/")
        self.assertEqual(resp.status_code, 200)
        token = json.loads(resp.data)["token"]
        self.assertEqual(len(token.split(".")), 3)
        resp = self.client.get("/", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 200)

        resp = self.client.post("/auth/renew/", data=json.dumps({"token": token}))
        self.assertEqual(resp.status_code, 200)
        token = json.loads(resp.data)["token"]
        self.assertEqual(len(token.split(".")), 3)
        resp = self.client.get("/", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 200)

    def testExpiredOk(self):
        before16mins = datetime.datetime.utcnow() - datetime.timedelta(minutes=16)
        with mock.patch("klangbecken.api_utils.datetime") as dt:
            dt.datetime.utcnow = mock.Mock(return_value=before16mins)
            dt.timedelta = mock.Mock(return_value=datetime.timedelta(minutes=15))
            resp = self.client.post("/auth/login/")
            self.assertEqual(resp.status_code, 200)
            token = json.loads(resp.data)["token"]
            self.assertEqual(len(token.split(".")), 3)

        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 401)
        resp = self.client.get("/", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 401)
        self.assertIn(b"Expired token", resp.data)

        resp = self.client.post("/auth/renew/", data=json.dumps({"token": token}))
        self.assertEqual(resp.status_code, 200)
        token = json.loads(resp.data)["token"]
        self.assertEqual(len(token.split(".")), 3)
        resp = self.client.get("/", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 200)

    def testExpiredNok(self):
        eightDaysAgo = datetime.datetime.utcnow() - datetime.timedelta(days=8)
        with mock.patch("klangbecken.api_utils.datetime") as dt:
            dt.datetime.utcnow = mock.Mock(return_value=eightDaysAgo)
            dt.timedelta = mock.Mock(return_value=datetime.timedelta(minutes=15))
            resp = self.client.post("/auth/login/")
            self.assertEqual(resp.status_code, 200)
            token = json.loads(resp.data)["token"]
            self.assertEqual(len(token.split(".")), 3)

        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 401)
        resp = self.client.get("/", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 401)

        resp = self.client.post("/auth/renew/", data=json.dumps({"token": token}))
        self.assertEqual(resp.status_code, 401)
        self.assertIn(b"Unrenewable expired token", resp.data)

    def testCorruptedToken(self):
        twentyMinutesAgo = datetime.datetime.utcnow() - datetime.timedelta(minutes=20)
        with mock.patch("klangbecken.api_utils.datetime") as dt:
            dt.datetime.utcnow = mock.Mock(return_value=twentyMinutesAgo)
            dt.timedelta = mock.Mock(return_value=datetime.timedelta(minutes=15))
            resp = self.client.post("/auth/login/")
            self.assertEqual(resp.status_code, 200)
            token = json.loads(resp.data)["token"]
            self.assertEqual(len(token.split(".")), 3)

        token = token[:-1]  # Corrupt token
        resp = self.client.get("/", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 401)
        self.assertIn(b"Invalid token", resp.data)

        resp = self.client.post("/auth/renew/", data=json.dumps({"token": token}))
        self.assertEqual(resp.status_code, 401)
        self.assertIn(b"Invalid token", resp.data)

    def testInvalidHeader(self):
        resp = self.client.post("/auth/login/")
        self.assertEqual(resp.status_code, 200)
        token = json.loads(resp.data)["token"]
        self.assertEqual(len(token.split(".")), 3)
        resp = self.client.get("/", headers={"Authorization": f"Something {token}"})
        self.assertEqual(resp.status_code, 401)
        self.assertIn(b"Invalid authorization header", resp.data)
