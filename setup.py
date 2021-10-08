import pathlib

from setuptools import find_packages, setup

here = pathlib.Path(__file__).parent.resolve()
long_description = (here / "README.md").read_text(encoding="utf-8")

setup(
    name="klangbecken",
    version="0.1.0",
    description="Klangbecken Audio Player",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/radiorabe/klangbecken",
    author="Marco Schmalz",
    author_email="marco@schess.ch",
    packages=find_packages(include=["klangbecken"]),
    platforms="linux",
    python_requires=">=3.6",
    license="AGPLv3",
    license_file="LICENSE",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Web Environment",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: GNU Affero General Public License v3",
        "Operating System :: POSIX",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
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
