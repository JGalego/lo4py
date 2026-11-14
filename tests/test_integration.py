from __future__ import annotations

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from lo4py import LO_VERSION, SOFFICE, convert, run

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not SOFFICE.is_file(), reason="bundled runtime not staged"),
]


@pytest.fixture(autouse=True)
def native_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    if os.name == "posix":
        # Avoid slow Java discovery through network and WSL PATH entries.
        monkeypatch.setenv("PATH", os.defpath)


def test_version_and_module_cli() -> None:
    version = ".".join(map(str, LO_VERSION))
    assert f"LibreOffice {version}" in run(["--version"], capture_output=True).stdout
    result = subprocess.run(
        [sys.executable, "-m", "lo4py", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert f"LibreOffice {version}" in result.stdout


def test_real_concurrent_conversion_and_roundtrip(tmp_path: Path) -> None:
    sources = [tmp_path / f"report {index}.txt" for index in range(2)]
    for source in sources:
        source.write_text("lo4py document conversion\n", encoding="utf-8")
    with ThreadPoolExecutor(max_workers=2) as pool:
        outputs = list(pool.map(convert, sources))
    for output in outputs:
        assert output.read_bytes().startswith(b"%PDF-")
        assert output.stat().st_size > 1000
    docx = convert(sources[0], to="docx")
    assert docx.read_bytes().startswith(b"PK")
    pdf = convert(docx, tmp_path / "roundtrip")
    assert pdf.read_bytes().startswith(b"%PDF-")
