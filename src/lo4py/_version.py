from typing import Final

__version__ = "26.8.3.0"
LO_BUILD = 1
LO_VERSION: Final = tuple(int(part) for part in __version__.split(".")[:3])
