from setuptools import setup, find_packages
from codecs import open
from os import path

here = path.abspath(path.dirname(__file__))

with open(path.join(here, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

setup(
    name='terra',
    version='0.1.dev1',
    description='Focused geographic search for Alberta Land Titles',
    long_description=long_description,
    url='https://github.com/jamwil/terra',
    author='James Williams',
    author_email='jamwil@gmail.com',
    py_modules=["terra"],
    install_requires=[
        'click',
        'numpy',
        'requests',
        'googlemaps'
    ],
    entry_points="""
        [console_scripts]
        terra=terra:terra
    """
)
