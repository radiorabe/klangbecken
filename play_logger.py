from __future__ import print_function

import os


def main():
    for key, value in os.environ.items():
        print(key, ':', value)
