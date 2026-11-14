"""Stage the official LibreOffice runtime without installing it on the host."""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import runpy
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent
PACKAGE = ROOT / "src" / "lo4py"
_version = runpy.run_path(str(PACKAGE / "_version.py"))
VERSION = ".".join(_version["__version__"].split(".")[:3]) + f".{_version['LO_BUILD']}"


@dataclass(frozen=True)
class Target:
    directory: str
    filename: str
    sha256: str
    wheel_platform: str


TARGETS = {
    ("linux", "x86_64"): Target(
        "deb/x86_64",
        f"LibreOffice_{VERSION}_Linux_x86-64_deb.tar.gz",
        "e7cd3538e85818ff9dd9bb65386769fde927011242aace5a144989f4000dcabf",
        "linux_x86_64",
    ),
    ("win32", "x86_64"): Target(
        "win/x86_64",
        f"LibreOffice_{VERSION}_Win_x86-64.msi",
        "0e6918c273eabbdbbd800ee0dacbbf130a14c13c2e4cec861b06dd59e015bf94",
        "win_amd64",
    ),
    ("darwin", "arm64"): Target(
        "mac/aarch64",
        f"LibreOffice_{VERSION}_MacOS_aarch64.dmg",
        "de943203795e5057785f65515063e2db5eb60b0bb6d8e2534fec59e5cc5fb988",
        "macosx_11_0_arm64",
    ),
    ("darwin", "x86_64"): Target(
        "mac/x86_64",
        f"LibreOffice_{VERSION}_MacOS_x86-64.dmg",
        "bb3c35d628780510915ad9e759d7ed898094d7985d01b2181bd1d4ecd94fd159",
        "macosx_11_0_x86_64",
    ),
}


def get_target() -> Target:
    machine = platform.machine().lower()
    machine = {"amd64": "x86_64", "aarch64": "arm64"}.get(machine, machine)
    try:
        return TARGETS[sys.platform, machine]
    except KeyError as error:
        raise RuntimeError(
            f"No official lo4py runtime for {sys.platform}/{machine}"
        ) from error


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(target: Target, cache: Path) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / target.filename
    if archive.exists():
        if _sha256(archive) != target.sha256:
            raise RuntimeError(f"SHA-256 mismatch for cached download: {archive}")
        return archive

    url = (
        "https://downloadarchive.documentfoundation.org/libreoffice/old/"
        f"{VERSION}/{target.directory}/{target.filename}"
    )
    print(f"Downloading {url}", flush=True)
    with TemporaryDirectory(prefix="lo4py-download-", dir=cache) as directory:
        temporary = Path(directory) / target.filename
        with (
            urllib.request.urlopen(url, timeout=120) as response,
            temporary.open("wb") as stream,
        ):
            shutil.copyfileobj(response, stream)
        if _sha256(temporary) != target.sha256:
            raise RuntimeError(f"SHA-256 mismatch for {url}")
        temporary.replace(archive)
    return archive


def _extract_tar(archive: Path, destination: Path) -> None:
    with tarfile.open(archive) as bundle:
        for member in bundle:
            path = destination / member.name
            if not path.resolve().is_relative_to(destination.resolve()):
                raise ValueError(f"Unsafe archive path: {member.name}")
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                path.parent.mkdir(parents=True, exist_ok=True)
                reader = bundle.extractfile(member)
                if reader is None:
                    raise ValueError(f"Unreadable archive entry: {member.name}")
                with reader, path.open("wb") as writer:
                    shutil.copyfileobj(reader, writer)
                path.chmod(member.mode & 0o777)
            else:
                raise ValueError(f"Unsupported archive entry: {member.name}")


def _single(paths: list[Path], description: str) -> Path:
    if len(paths) != 1:
        raise RuntimeError(f"Expected one {description}, found {len(paths)}")
    return paths[0]


def _extract_linux(archive: Path, work: Path, staging: Path) -> None:
    packages = work / "packages"
    _extract_tar(archive, packages)
    debs = sorted(packages.rglob("*.deb"))
    if not debs:
        raise RuntimeError(f"No Debian packages in {archive}")
    extracted = work / "extracted"
    for deb in debs:
        subprocess.run(["dpkg-deb", "--extract", deb, extracted], check=True)
    home = _single(
        list((extracted / "opt").glob("libreoffice*")), "LibreOffice installation"
    )
    shutil.copytree(home, staging)


def _extract_windows(archive: Path, work: Path, staging: Path) -> None:
    extracted = work / "extracted"
    log = work / "msiexec.log"
    result = subprocess.run(
        [
            "msiexec",
            "/a",
            str(archive.resolve()),
            "/qn",
            "/norestart",
            f"TARGETDIR={extracted.resolve()}",
            "/L*v",
            str(log),
        ],
        check=False,
    )
    if result.returncode not in (0, 3010):
        details = (
            log.read_text(encoding="utf-16", errors="replace") if log.exists() else ""
        )
        raise RuntimeError(f"MSI extraction failed ({result.returncode}):\n{details}")
    executable = _single(list(extracted.rglob("soffice.com")), "soffice.com")
    shutil.copytree(executable.parent.parent, staging)


def _extract_macos(archive: Path, work: Path, staging: Path) -> None:
    mount = work / "mount"
    subprocess.run(
        [
            "hdiutil",
            "attach",
            "-readonly",
            "-nobrowse",
            "-mountpoint",
            mount,
            archive,
        ],
        check=True,
    )
    try:
        app = _single(list(mount.glob("*.app")), "LibreOffice application")
        staging.mkdir()
        shutil.copytree(app, staging / "LibreOffice.app")
    finally:
        subprocess.run(["hdiutil", "detach", mount], check=True)


def build_runtime(cache: Path | None = None) -> Path:
    target = get_target()
    destination = PACKAGE / "runtime"
    executable = (
        Path("LibreOffice.app/Contents/MacOS/soffice")
        if sys.platform == "darwin"
        else Path(
            "program/soffice.com" if sys.platform == "win32" else "program/soffice"
        )
    )
    marker = destination / ".lo4py-version"
    stamp = f"{VERSION}\n{target.sha256}\n"
    if destination.exists():
        if (
            marker.is_file()
            and marker.read_text(encoding="ascii") == stamp
            and (destination / executable).is_file()
        ):
            return destination
        raise RuntimeError(
            f"Runtime at {destination} is incomplete or for a different release. "
            "Remove that directory explicitly before rebuilding."
        )

    archive = download(target, cache if cache is not None else ROOT / ".cache/lo4py")
    with TemporaryDirectory(prefix="lo4py-build-", dir=PACKAGE) as temporary:
        work = Path(temporary)
        staging = work / "runtime"
        if sys.platform == "linux":
            _extract_linux(archive, work, staging)
        elif sys.platform == "win32":
            _extract_windows(archive, work, staging)
        else:
            _extract_macos(archive, work, staging)
        if not (staging / executable).is_file():
            raise RuntimeError(f"Extracted runtime is missing {executable}")
        (staging / ".lo4py-version").write_text(stamp, encoding="ascii")
        os.replace(staging, destination)
    print(f"Staged LibreOffice {VERSION} at {destination}", flush=True)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, help="Directory for verified downloads")
    build_runtime(parser.parse_args().cache)
