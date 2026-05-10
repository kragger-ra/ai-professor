"""Tests package initialization.

This sets up the Python path for all tests to easily import modules from the src directory.
"""
import os
import sys

# Add the src directory to the Python path
src_path = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)