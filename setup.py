from setuptools import setup

setup(
    name='klangbecken',
    version='0.0.10',
    description='Klangbecken API',
    url='https://github.com/radiorabe/klangbecken',
    author='Marco Schmalz',
    author_email='marco@schess.ch ',
    py_modules=['klangbecken_api', 'saemubox_listener', 'play_logger'],
    license='AGPLv3',
    classifiers=[
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
        'Programming Language :: Python :: 3.7',
        'Topic :: Internet :: WWW/HTTP :: WSGI',
    ],
    install_requires=['werkzeug', 'mutagen', 'six'],
    extras_require={
        'test': ['tox', 'coverage', 'mock', 'flake8'],
    },
    entry_points={
        'console_scripts': [
            'saemubox-listener=saemubox_listener:main',
            'klangbecken-import=klangecken_api:import_files',
            'klangbecken-fsck=klangbecken_api:fsck',
            'klangbecken-play-logger=play_logger:main',
        ],
    }
)
