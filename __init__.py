"""NetTyan project package initialization.

This makes the src directory accessible as a package without having to use 'src.' prefix.
"""

import os
import sys

# Add src directory to Python path so imports work without 'src.' prefix
src_path = os.path.join(os.path.dirname(__file__), 'src')
if src_path not in sys.path:
    sys.path.insert(0, src_path)

# Import the version from src/__init__.py
from src import __version__

__all__ = ['__version__']