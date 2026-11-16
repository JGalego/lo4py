from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from lo4py import Extracted, _uno, extract, recalculate


@pytest.fixture
def call(monkeypatch: pytest.MonkeyPatch) -> Mock:
    mock = Mock(return_value={"kind": "text", "text": "hello", "sheets": {}})
    monkeypatch.setattr(_uno, "_call", mock)
    return mock


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "book.xlsx"
    path.write_bytes(b"source")
    return path


def test_extract_wraps_worker_result(call: Mock, source: Path) -> None:
    assert extract(source, recalculate=False, timeout=5) == Extracted(
        "text", "hello", {}
    )
    call.assert_called_once_with("extract", source.resolve(), 5, recalculate=False)


def test_recalculate_validates_before_starting_office(
    call: Mock, source: Path, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="must end in"):
        recalculate(source, tmp_path / "out.csv")
    with pytest.raises(ValueError, match="replace the source"):
        recalculate(source, source, overwrite=True)
    existing = tmp_path / "existing.xlsx"
    existing.write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        recalculate(source, existing)
    call.assert_not_called()
    assert existing.read_bytes() == b"keep"


def test_recalculate_creates_parent_and_returns_output(
    call: Mock, source: Path, tmp_path: Path
) -> None:
    output = tmp_path / "nested" / "book.ods"
    assert recalculate(source, output) == output
    assert output.parent.is_dir()
    assert call.call_args.kwargs["suffix"] == ".ods"


def test_environment_drops_host_python_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTHONPATH", "/host")
    monkeypatch.setenv("PYTHONHOME", "/host")
    environment = _uno._environment()
    assert "PYTHONPATH" not in environment
    assert "PYTHONHOME" not in environment
    assert environment["PYTHONIOENCODING"] == "utf-8"
