from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final

StrPath = str | os.PathLike[str]

_runtime = Path(__file__).resolve().parent / "runtime"
LO_HOME: Final = _runtime / "LibreOffice.app" if sys.platform == "darwin" else _runtime
SOFFICE: Final = LO_HOME / (
    Path("Contents/MacOS/soffice")
    if sys.platform == "darwin"
    else Path("program/soffice.com" if sys.platform == "win32" else "program/soffice")
)


class ConversionError(RuntimeError):
    """LibreOffice exited successfully but did not produce the requested file."""


def run(
    args: Sequence[StrPath] = (),
    *,
    check: bool = True,
    capture_output: bool = False,
    timeout: float | None = None,
    cwd: StrPath | None = None,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run bundled LibreOffice with native options and text-mode output."""
    if not SOFFICE.is_file():
        raise FileNotFoundError(
            f"Bundled LibreOffice is missing: {SOFFICE}. "
            "Install a lo4py binary wheel, or run python build_runtime.py "
            "in a source checkout."
        )
    return subprocess.run(
        [SOFFICE, *args],
        check=check,
        capture_output=capture_output,
        text=True,
        timeout=timeout,
        cwd=cwd,
        env=env,
    )


def convert(
    source: StrPath,
    output_dir: StrPath | None = None,
    *,
    to: str = "pdf",
    overwrite: bool = False,
    timeout: float | None = 120,
) -> Path:
    """Convert a document using an isolated headless LibreOffice process.

    ``to`` accepts a native extension, filter name, and optional JSON filter
    options, for example ``pdf:writer_pdf_Export``. Auxiliary export files
    are retained. Existing outputs are not overwritten unless requested.
    """
    source = Path(source).resolve(strict=True)
    if not source.is_file():
        raise IsADirectoryError(source)

    extension, separator, options = to.partition(":")
    if re.fullmatch(r"[A-Za-z0-9]+", extension) is None:
        raise ValueError("to must start with a file extension, e.g. 'pdf'")
    extension = extension.lower()
    to = extension + separator + options

    destination = source.parent if output_dir is None else Path(output_dir).resolve()
    output = destination / f"{source.stem}.{extension}"
    if output == source or (output.exists() and output.samefile(source)):
        raise ValueError("The output would replace the source document")
    if output.exists() and not overwrite:
        raise FileExistsError(output)
    destination.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(prefix="lo4py-") as temporary:
        work = Path(temporary)
        staging = work / "output"
        staging.mkdir()
        result = run(
            [
                f"-env:UserInstallation={(work / 'profile').as_uri()}",
                "--headless",
                "--nologo",
                "--nodefault",
                "--norestore",
                "--convert-to",
                to,
                "--outdir",
                staging,
                source,
            ],
            capture_output=True,
            timeout=timeout,
        )
        expected = staging / output.name
        if not expected.is_file():
            details = "\n".join(
                text.strip() for text in (result.stdout, result.stderr) if text
            )
            raise ConversionError(
                f"LibreOffice did not create {output.name} from {source}."
                + (f"\n{details}" if details else "")
            )

        artifacts = sorted(staging.rglob("*"))
        for artifact in artifacts:
            target = destination / artifact.relative_to(staging)
            if not target.resolve().is_relative_to(destination):
                raise ValueError(f"Export path escapes output_dir: {target}")
            if target.exists() and target.samefile(source):
                raise ValueError("The output would replace the source document")
            if artifact.is_file() and (
                target.is_symlink() or (target.exists() and not overwrite)
            ):
                raise FileExistsError(target)

        for artifact in artifacts:
            target = destination / artifact.relative_to(staging)
            if artifact.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with (
                    artifact.open("rb") as reader,
                    target.open("wb" if overwrite else "xb") as writer,
                ):
                    shutil.copyfileobj(reader, writer)
    return output
