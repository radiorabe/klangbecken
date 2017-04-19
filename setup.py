from setuptools import setup

setup(
    name='KlangbeckenAPI',
    version='0.0.3',
    description='Klangbecken API',
    url='https://github.com/radiorabe/klangbecken',
    author='Marco Schmalz',
    author_email='marco@schess.ch ',
    py_modules=['klangbecken_api', 'saemubox_listener'],
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
        'Topic :: Internet :: WWW/HTTP :: WSGI',
    ],
    install_requires=['werkzeug', 'mutagen'],
    extras_require={
        'test': ['tox', 'coverage'],
    },
    entry_points = {
        'console_scripts': ['saemubox-listener=saemubox_listener:main'],
    }
)
