import unittest


class BackendTest(unittest.TestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_application(self):
        from klangbecken_api import application, WebAPI

        self.assertTrue(isinstance(application, WebAPI))
        self.assertTrue(callable(application))
