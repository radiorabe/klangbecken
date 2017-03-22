from setuptools import setup

setup(
    name='KlangbeckenAPI',
    version='0.0.1',
    description='Klangbecken API',
    url='https://github.com/radiorabe/klangbecken',
    author='Marco Schmalz',
    author_email='marco@schess.ch ',
    py_modules=['klangbecken_api'],
    license='AGPLv3',

    # See https://pypi.python.org/pypi?%3Aaction=list_classifiers
    classifiers=[
        # How mature is this project? Common values are
        #   3 - Alpha
        #   4 - Beta
        #   5 - Production/Stable
        'Development Status :: 3 - Alpha',
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: GNU Affero General Public License v3',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Topic :: Internet :: WWW/HTTP :: WSGI',
    ],
    install_requires=['werkzeug', 'mutagen'],
    extras_require={
        'test': ['tox', 'coverage'],
    },
)
