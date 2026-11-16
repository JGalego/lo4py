from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Final

from . import _api
from ._api import StrPath

_WORKER: Final = Path(__file__).resolve().with_name("_uno_worker.py")
_SPREADSHEET_SUFFIXES: Final = (".xlsx", ".xls", ".ods")
_GRACE: Final = 30.0


class OfficeError(RuntimeError):
    """LibreOffice could not complete a document operation."""


@dataclass(frozen=True)
class Extracted:
    """Content read from a document by :func:`extract`.

    ``kind`` is ``"text"``, ``"spreadsheet"``, ``"presentation"`` or
    ``"drawing"``. ``sheets`` maps sheet names to rows of computed values and
    is empty for every other kind.
    """

    kind: str
    text: str
    sheets: dict[str, list[list[float | str]]] = field(default_factory=dict)


@lru_cache(maxsize=1)
def _runtime_python() -> tuple[Path, Path]:
    """Return the bundled interpreter and the directory holding ``uno.py``."""
    home = _api.LO_HOME
    program_dirs = [home / "program", home / "Contents" / "Resources", home]
    program = next((path for path in program_dirs if (path / "uno.py").is_file()), None)
    if program is None:
        program = next((path.parent for path in sorted(home.rglob("uno.py"))), None)
    if program is None:
        raise OfficeError(f"The bundled runtime has no uno.py under {home}")

    names = ("python", "python.exe", "python3", "python3.exe")
    search = [program, *program.parent.glob("Frameworks/*/Versions/*/bin")]
    search += list(home.glob("Contents/Frameworks/*/Versions/*/bin"))
    for directory in search:
        for name in names:
            candidate = directory / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate, program
    raise OfficeError(f"The bundled runtime has no Python interpreter near {program}")


def python_executable() -> Path:
    """Path of the Python interpreter bundled with LibreOffice."""
    return _runtime_python()[0]


def _environment() -> dict[str, str]:
    # The bundled launcher builds its own module path; host values would leak in.
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("PYTHON")
    }
    environment["PYTHONIOENCODING"] = "utf-8"
    return environment


def _call(
    operation: str, source: Path, timeout: float, **parameters: Any
) -> dict[str, Any]:
    interpreter, program = _runtime_python()
    if not _api.SOFFICE.is_file():
        raise FileNotFoundError(f"Bundled LibreOffice is missing: {_api.SOFFICE}")
    with TemporaryDirectory(prefix="lo4py-") as temporary:
        work = Path(temporary)
        request = {
            "operation": operation,
            "source": str(source),
            "program": str(program),
            "soffice": str(_api.SOFFICE),
            "profile": (work / "profile").as_uri(),
            "timeout": timeout,
            **parameters,
        }
        if "output" in parameters:
            request["output"] = str(work / f"output{parameters['suffix']}")
        completed = subprocess.run(
            [interpreter, _WORKER],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout + _GRACE,
            env=_environment(),
            cwd=work,
            check=False,
        )
        try:
            result = json.loads(completed.stdout)
        except ValueError:
            details = (completed.stderr or completed.stdout).strip()
            raise OfficeError(
                f"The LibreOffice worker failed with status {completed.returncode}."
                + (f"\n{details}" if details else "")
            ) from None
        if not result.get("ok"):
            raise OfficeError(result.get("error", "Unknown LibreOffice error"))
        if "output" in parameters:
            staged = work / f"output{parameters['suffix']}"
            if not staged.is_file():
                raise OfficeError("LibreOffice did not produce the recalculated file")
            _publish(staged, Path(parameters["output"]), parameters["overwrite"])
        return result  # type: ignore[no-any-return]


def _publish(staged: Path, destination: Path, overwrite: bool) -> None:
    if destination.is_symlink() or (destination.exists() and not overwrite):
        raise FileExistsError(destination)
    with (
        staged.open("rb") as reader,
        destination.open("wb" if overwrite else "xb") as writer,
    ):
        shutil.copyfileobj(reader, writer)


def _resolve_source(source: StrPath) -> Path:
    path = Path(source).resolve(strict=True)
    if not path.is_file():
        raise IsADirectoryError(path)
    return path


def extract(
    source: StrPath, *, recalculate: bool = True, timeout: float = 120
) -> Extracted:
    """Read text, and for spreadsheets computed cell values, from a document.

    The document is opened read-only with macros and link updates disabled, in
    an isolated LibreOffice process. Spreadsheets are fully recalculated first
    unless ``recalculate`` is false, so formulas written by tools that do not
    store results still return values.
    """
    path = _resolve_source(source)
    result = _call("extract", path, timeout, recalculate=recalculate)
    return Extracted(result["kind"], result["text"], result["sheets"])


def recalculate(
    source: StrPath,
    output: StrPath,
    *,
    overwrite: bool = False,
    timeout: float = 120,
) -> Path:
    """Recalculate every formula in a spreadsheet and save the result.

    ``output`` must end in ``.xlsx``, ``.xls`` or ``.ods``. The source is never
    modified, and an existing output is refused unless ``overwrite`` is true.
    """
    path = _resolve_source(source)
    destination = Path(output).resolve()
    suffix = destination.suffix.lower()
    if suffix not in _SPREADSHEET_SUFFIXES:
        raise ValueError("output must end in .xlsx, .xls or .ods")
    if destination == path or (destination.exists() and destination.samefile(path)):
        raise ValueError("The output would replace the source document")
    if destination.is_symlink() or (destination.exists() and not overwrite):
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    _call(
        "recalculate",
        path,
        timeout,
        output=str(destination),
        suffix=suffix,
        overwrite=overwrite,
    )
    return destination
