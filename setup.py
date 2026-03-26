"""Setup script for NetTyan project.

This makes the project installable in development mode to simplify imports.
"""

from setuptools import setup, find_packages

setup(
    name="NetTyan",
    version="0.0.5",  # Matches src/__init__.py version
    package_dir={"": "src"},
    packages=find_packages(where="src"),
)