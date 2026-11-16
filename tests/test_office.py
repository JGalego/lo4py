from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from lo4py import OfficeError, extract, python_executable, recalculate
from lo4py._api import SOFFICE

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not SOFFICE.is_file(), reason="bundled runtime not staged"),
]

NAMESPACES = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"'
)
SHEET = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document {NAMESPACES} office:version="1.3"
 office:mimetype="application/vnd.oasis.opendocument.spreadsheet">
<office:body><office:spreadsheet><table:table table:name="Data">
<table:table-row>
<table:table-cell office:value-type="float" office:value="20"/>
<table:table-cell office:value-type="float" office:value="22"/>
<table:table-cell table:formula="=SUM([.A1:.B1])*2"/>
</table:table-row>
</table:table></office:spreadsheet></office:body></office:document>
"""
LETTER = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document {NAMESPACES} office:version="1.3"
 office:mimetype="application/vnd.oasis.opendocument.text">
<office:body><office:text>
<text:p>Resilient documents</text:p><text:p>Café ✓</text:p>
</office:text></office:body></office:document>
"""


@pytest.fixture(autouse=True)
def native_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    if os.name == "posix":
        # Avoid slow Java discovery through network and WSL PATH entries.
        monkeypatch.setenv("PATH", os.defpath)


def test_bundled_python_is_discoverable() -> None:
    assert python_executable().is_file()


def test_extract_recalculates_spreadsheet(tmp_path: Path) -> None:
    source = tmp_path / "data.fods"
    source.write_text(SHEET, encoding="utf-8")
    result = extract(source)
    assert result.kind == "spreadsheet"
    assert result.sheets == {"Data": [[20.0, 22.0, 84.0]]}
    assert result.text == "20.0\t22.0\t84.0"


def test_extract_text_document(tmp_path: Path) -> None:
    source = tmp_path / "letter.fodt"
    source.write_text(LETTER, encoding="utf-8")
    result = extract(source)
    assert result.kind == "text"
    assert result.text == "Resilient documents\nCafé ✓"
    assert result.sheets == {}


def test_recalculate_saves_cached_values(tmp_path: Path) -> None:
    source = tmp_path / "data.fods"
    source.write_text(SHEET, encoding="utf-8")
    output = recalculate(source, tmp_path / "out" / "data.xlsx")
    assert output.read_bytes().startswith(b"PK")
    assert extract(output, recalculate=False).sheets["Data"] == [[20.0, 22.0, 84.0]]
    with pytest.raises(FileExistsError):
        recalculate(source, output)
    assert recalculate(source, output, overwrite=True) == output


def test_recalculate_rejects_non_spreadsheets(tmp_path: Path) -> None:
    source = tmp_path / "letter.fodt"
    source.write_text(LETTER, encoding="utf-8")
    with pytest.raises(OfficeError, match="spreadsheets"):
        recalculate(source, tmp_path / "letter.xlsx")
    assert not (tmp_path / "letter.xlsx").exists()


def test_missing_source_is_reported(tmp_path: Path) -> None:
    (tmp_path / "x.fods").write_text(SHEET, encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        extract(tmp_path / "missing.xlsx")
    with pytest.raises(ValueError, match="must end in"):
        recalculate(tmp_path / "x.fods", tmp_path / "out.txt")


def office_processes() -> list[str]:
    found = []
    for entry in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            arguments = entry.read_bytes().split(b"\0")
        except OSError:
            continue
        if any(item.startswith(b"--accept=pipe,name=lo4py-") for item in arguments):
            found.append(entry.parent.name)
    return found


@pytest.mark.skipif(not Path("/proc/self").exists(), reason="needs /proc")
def test_timeout_reports_error_and_leaves_no_process(tmp_path: Path) -> None:
    source = tmp_path / "data.fods"
    source.write_text(SHEET, encoding="utf-8")
    started = time.monotonic()
    with pytest.raises(OfficeError):
        extract(source, timeout=0.05)
    assert time.monotonic() - started < 8
    time.sleep(0.5)
    assert office_processes() == []
