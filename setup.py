from setuptools import find_packages, setup

setup(
    name="klangbecken",
    version="0.0.30",
    description="Klangbecken Audio Player",
    url="https://github.com/radiorabe/klangbecken",
    author="Marco Schmalz",
    author_email="marco@schess.ch ",
    packages=find_packages(include=["klangbecken"]),
    python_requires=">=3.6",
    license="AGPLv3",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Environment :: Web Environment",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: GNU Affero General Public License v3",
        "Operating System :: POSIX",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Topic :: Internet :: WWW/HTTP :: WSGI",
        "Topic :: Internet :: WWW/HTTP :: WSGI :: Application",
    ],
    install_requires=["docopt", "mutagen", "PyJWT >= 2.0.0", "Werkzeug >= 2.0.0"],
    extras_require={
        "dev": ["tox", "black", "isort"],
        "test": ["flake8", "coverage"],
    },
    entry_points={"console_scripts": ["klangbecken=klangbecken.cli:main"]},
)
