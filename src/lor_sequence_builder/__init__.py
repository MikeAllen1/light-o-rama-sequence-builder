"""Light-O-Rama S6 Sequence Builder."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("light-o-rama-sequence-builder")
except PackageNotFoundError:
    __version__ = "0+unknown"
