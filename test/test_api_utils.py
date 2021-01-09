import doctest

import klangbecken.api_utils


def load_tests(loader, tests, ignore):
    # load doctests
    tests.addTests(doctest.DocTestSuite(klangbecken.api_utils))
    return tests
