from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import unquote, urlsplit

import pytest

from lo4py import ConversionError, _api, convert, run
from lo4py import __main__ as cli


@pytest.fixture
def native_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Mock:
    executable = tmp_path / "soffice"
    executable.touch()
    monkeypatch.setattr(_api, "SOFFICE", executable)
    mock = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
    monkeypatch.setattr(_api.subprocess, "run", mock)
    return mock


@pytest.fixture
def document(tmp_path: Path) -> Path:
    source = tmp_path / "document with spaces.docx"
    source.write_bytes(b"source document")
    return source


def test_run_preserves_native_options(native_run: Mock, tmp_path: Path) -> None:
    result = run(
        ["--writer", tmp_path / "file.odt"],
        check=False,
        capture_output=True,
        timeout=10,
        cwd=tmp_path,
        env={"HOME": str(tmp_path)},
    )
    assert result is native_run.return_value
    native_run.assert_called_once_with(
        [_api.SOFFICE, "--writer", tmp_path / "file.odt"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
        cwd=tmp_path,
        env={"HOME": str(tmp_path)},
    )


def test_run_missing_bundle_does_not_use_system_office(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(_api, "SOFFICE", tmp_path / "missing")
    with pytest.raises(FileNotFoundError, match="Bundled LibreOffice is missing"):
        run(["--version"])


def _outdir(command: list[str | Path]) -> Path:
    return Path(command[command.index("--outdir") + 1])


def _export(
    command: list[str | Path], **kwargs: object
) -> subprocess.CompletedProcess[str]:
    staging = _outdir(command)
    source = Path(command[-1])
    (staging / f"{source.stem}.pdf").write_bytes(b"%PDF-1.7\nnew output")
    return subprocess.CompletedProcess(command, 0, "converted", "")


def test_convert_checks_new_output_and_keeps_source(
    native_run: Mock, document: Path, tmp_path: Path
) -> None:
    native_run.side_effect = _export
    destination = tmp_path / "new output"
    output = convert(document, destination)
    assert output == destination / f"{document.stem}.pdf"
    assert output.read_bytes().startswith(b"%PDF")
    assert document.read_bytes() == b"source document"
    command = native_run.call_args.args[0]
    assert command[-1] == document
    assert "--headless" in command
    assert not _outdir(command).exists()
    assert native_run.call_args.kwargs["timeout"] == 120


def test_convert_uses_unique_profiles_and_preserves_filter_options(
    native_run: Mock, document: Path
) -> None:
    native_run.side_effect = _export
    filter_spec = 'PDF:writer_pdf_Export:{"PageRange":{"type":"string","value":"1"}}'
    convert(document, to=filter_spec)
    convert(document, to=filter_spec, overwrite=True, timeout=None)
    commands = [call.args[0] for call in native_run.call_args_list]
    profiles = [
        next(arg for arg in command if str(arg).startswith("-env:UserInstallation="))
        for command in commands
    ]
    assert profiles[0] != profiles[1]
    for command, profile in zip(commands, profiles, strict=True):
        assert command[command.index("--convert-to") + 1] == (
            "pdf:writer_pdf_Export:" + filter_spec.split(":", 2)[2]
        )
        uri = str(profile).split("=", 1)[1]
        assert urlsplit(uri).scheme == "file"
        assert not Path(unquote(urlsplit(uri).path)).exists()
    assert native_run.call_args.kwargs["timeout"] is None


def test_convert_refuses_existing_output(native_run: Mock, document: Path) -> None:
    output = document.with_suffix(".pdf")
    output.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        convert(document)
    native_run.assert_not_called()
    assert output.read_bytes() == b"existing"


def test_exit_zero_with_stale_output_is_not_success(
    native_run: Mock, document: Path
) -> None:
    output = document.with_suffix(".pdf")
    output.write_bytes(b"existing")
    native_run.return_value = subprocess.CompletedProcess(
        [], 0, "", "Error: source file could not be loaded"
    )
    with pytest.raises(ConversionError, match="source file could not be loaded"):
        convert(document, overwrite=True)
    assert output.read_bytes() == b"existing"


@pytest.mark.parametrize(
    "error",
    [
        subprocess.CalledProcessError(1, ["soffice"], stderr="failed"),
        subprocess.TimeoutExpired(["soffice"], 1),
    ],
)
def test_native_failure_propagates_and_cleans_temporary_files(
    native_run: Mock, document: Path, error: Exception
) -> None:
    native_run.side_effect = error
    with pytest.raises(type(error)):
        convert(document)
    assert not _outdir(native_run.call_args.args[0]).exists()
    assert not document.with_suffix(".pdf").exists()


def test_html_auxiliary_exports_are_kept(
    native_run: Mock, document: Path, tmp_path: Path
) -> None:
    def export(
        command: list[str | Path], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        staging = _outdir(command)
        (staging / f"{document.stem}.html").write_text("html", encoding="utf-8")
        (staging / "images").mkdir()
        (staging / "images" / "image.png").write_bytes(b"image")
        return subprocess.CompletedProcess(command, 0, "", "")

    native_run.side_effect = export
    destination = tmp_path / "html"
    output = convert(document, destination, to="html")
    assert output.read_text(encoding="utf-8") == "html"
    assert (destination / "images" / "image.png").read_bytes() == b"image"
    (destination / "images" / "image.png").write_bytes(b"keep")
    output.unlink()
    with pytest.raises(FileExistsError):
        convert(document, destination, to="html")
    assert not output.exists()
    assert (destination / "images" / "image.png").read_bytes() == b"keep"


@pytest.mark.parametrize("to", ["", "../pdf", ".pdf", "pdf/other", "pdf\n"])
def test_invalid_filters_fail_before_launch(
    native_run: Mock, document: Path, to: str
) -> None:
    with pytest.raises(ValueError):
        convert(document, to=to)
    native_run.assert_not_called()


def test_conversion_never_replaces_source(native_run: Mock, document: Path) -> None:
    with pytest.raises(ValueError, match="replace the source"):
        convert(document, to="docx", overwrite=True)
    native_run.assert_not_called()


def test_conversion_never_truncates_a_hardlinked_source(
    native_run: Mock, document: Path
) -> None:
    document.with_suffix(".pdf").hardlink_to(document)
    with pytest.raises(ValueError, match="replace the source"):
        convert(document, overwrite=True)
    native_run.assert_not_called()
    assert document.read_bytes() == b"source document"


def test_missing_input_fails_before_launch(native_run: Mock, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        convert(tmp_path / "missing.docx")
    with pytest.raises(IsADirectoryError):
        convert(tmp_path)
    native_run.assert_not_called()


def test_cli_forwards_options_and_exit_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock = Mock(return_value=subprocess.CompletedProcess([], 7))
    monkeypatch.setattr(cli, "run", mock)
    monkeypatch.setattr(sys, "argv", ["lo4py", "--headless", "--version"])
    assert cli.main() == 7
    mock.assert_called_once_with(["--headless", "--version"], check=False)


def test_cli_reports_launch_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "run", Mock(side_effect=FileNotFoundError("missing")))
    assert cli.main() == 1
    assert "lo4py: missing" in capsys.readouterr().err
