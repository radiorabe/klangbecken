from setuptools import setup

setup(
    name='klangbecken',
    version='0.0.12',
    description='Klangbecken Audio Player',
    url='https://github.com/radiorabe/klangbecken',
    author='Marco Schmalz',
    author_email='marco@schess.ch ',
    py_modules=['klangbecken', 'saemubox_listener'],
    license='AGPLv3',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: GNU Affero General Public License v3',
        'Operating System :: POSIX',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3 :: Only',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Topic :: Internet :: WWW/HTTP :: WSGI',
    ],
    install_requires=['docopt', 'mutagen', 'PyJWT', 'six', 'Werkzeug'],
    extras_require={
        'test': ['tox', 'coverage', 'mock', 'flake8'],
    },
    entry_points={
        'console_scripts': [
            'klangbecken=klangbecken:main',
            'saemubox-listener=saemubox_listener:main',
        ],
    }
)
