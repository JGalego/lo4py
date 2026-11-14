"""LibreOffice shipped in a Python package."""

from ._api import LO_HOME, SOFFICE, ConversionError, convert, run
from ._version import LO_VERSION, __version__

__all__ = [
    "LO_HOME",
    "LO_VERSION",
    "SOFFICE",
    "ConversionError",
    "__version__",
    "convert",
    "run",
]
