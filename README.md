<p align="center">
  <img src="assets/logo.svg" alt="Office document and snake emblem" width="128">
</p>

<h1 align="center">lo4py</h1>

<p align="center"><strong>LibreOffice power. Python simplicity.</strong></p>

<p align="center">
  <a href="https://github.com/JGalego/lo4py/releases/latest"><img src="https://img.shields.io/github/v/release/JGalego/lo4py?style=flat-square&amp;color=16a34a" alt="Latest release"></a>
  <a href="https://github.com/JGalego/lo4py/actions/workflows/test.yml"><img src="https://img.shields.io/github/actions/workflow/status/JGalego/lo4py/test.yml?branch=main&amp;style=flat-square&amp;label=tests" alt="Tests"></a>
  <a href="https://github.com/JGalego/lo4py/blob/main/pyproject.toml"><img src="https://img.shields.io/badge/Python-3.10%2B-3776ab?style=flat-square&amp;logo=python&amp;logoColor=white" alt="Python 3.10 or newer"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/wrapper-MIT-64748b?style=flat-square" alt="Wrapper license: MIT"></a>
</p>

LibreOffice shipped in a Python package. No system installation, no first-use download, no Python runtime dependencies.

## Install

lo4py is distributed exclusively through [GitHub Releases](https://github.com/JGalego/lo4py/releases/latest), not PyPI. Download the wheel matching your platform:

| Platform | Wheel suffix |
| --- | --- |
| Linux x86-64 | `linux_x86_64.whl` |
| Windows x86-64 | `win_amd64.whl` |
| macOS Apple Silicon | `macosx_11_0_arm64.whl` |
| macOS Intel | `macosx_11_0_x86_64.whl` |

Install the downloaded file. For example, on Linux:

```sh
python -m pip install --no-index ./lo4py-26.8.3.1-py3-none-linux_x86_64.whl
```

For a project managed by uv, use `uv add ./lo4py-26.8.3.1-py3-none-linux_x86_64.whl` instead.

Binary wheels contain the full official LibreOffice distribution, not just a PDF converter. Downloads are large; budget roughly 1 GB of installed space.

## Python

```python
from lo4py import convert

pdf = convert("report.docx")
pdf = convert("report.docx", "output", overwrite=True)
document = convert("report.docx", "output", to="odt")
```

`convert(source, output_dir=None, *, to="pdf", overwrite=False, timeout=120)` returns the output `Path`. The default output directory is the source directory. The source must exist. Outputs never replace the source itself. Existing files are refused unless `overwrite=True`; auxiliary export files, such as HTML images, are kept too.

Each conversion uses a temporary profile and staging directory. Independent jobs can run concurrently without sharing a LibreOffice session. Existing outputs cannot be mistaken for a successful conversion.

Native export filters and their JSON options work unchanged:

```python
pdf = convert(
    "report.docx",
    to='pdf:writer_pdf_Export:{"PageRange":{"type":"string","value":"1-3"}}',
)
```

Failures raise `FileNotFoundError`, `FileExistsError`, `ValueError`, `subprocess.CalledProcessError`, or `subprocess.TimeoutExpired`. LibreOffice sometimes reports conversion errors with exit code zero: `ConversionError` detects missing output and includes its diagnostics.

### Read and recalculate

```python
from lo4py import extract, recalculate

content = extract("model.xlsx")
print(content.sheets["Sheet1"])  # computed values, even if the file stored none
print(extract("report.docx").text)

recalculate("model.xlsx", "model-calculated.xlsx")
```

`extract(source, *, recalculate=True, timeout=120)` returns `Extracted(kind, text, sheets)`. `kind` is `"text"`, `"spreadsheet"`, `"presentation"` or `"drawing"`; `sheets` maps sheet names to rows of values for spreadsheets. `recalculate(source, output, *, overwrite=False, timeout=120)` recalculates every formula and saves an `.xlsx`, `.xls` or `.ods` copy with the results stored, which is useful for files written by libraries that cannot evaluate formulas. The source is never modified and existing outputs are refused unless `overwrite=True`.

Documents open read-only (recalculate excepted) with macros and link updates disabled. Each call starts an isolated LibreOffice that is stopped afterwards. The UNO work happens in LibreOffice's bundled Python, so nothing is imported into your interpreter. `python_executable()` returns that interpreter if you want to run your own UNO scripts. Failures raise `OfficeError`.

### Native LibreOffice

```python
from lo4py import LO_HOME, LO_VERSION, SOFFICE, run

print(LO_HOME)  # pathlib.Path to the bundled installation
print(LO_VERSION)  # (26, 8, 3)
print(SOFFICE)  # pathlib.Path to the executable
print(run(["--version"], capture_output=True).stdout)
run(["--writer", "report.docx"])
```

`run` accepts native arguments and `check`, `capture_output`, `timeout`, `cwd`, and `env`. It returns `subprocess.CompletedProcess[str]`, uses text output, and checks the exit status by default. Unlike `convert`, it does not change the profile or add headless options. For streaming, async processes, or other subprocess options, use `SOFFICE` directly:

```python
import subprocess
from lo4py import SOFFICE

process = subprocess.Popen([SOFFICE, "--headless", "--version"])
process.wait()
```

## Command line

```sh
lo4py --version
lo4py --headless --convert-to pdf --outdir output report.docx
python -m lo4py --help
uvx --from ./lo4py-26.8.3.1-py3-none-linux_x86_64.whl lo4py --version
```

All arguments are passed directly to LibreOffice; the exit status is preserved. Native CLI conversion has LibreOffice's own profile and overwrite behavior. Use the Python `convert` helper for isolated jobs and checked output.

## Platforms and limits

- Python 3.10 or newer.
- Linux x86-64: glibc 2.28+, an x86-64-v2 CPU, and distribution-provided native libraries. Wheels use the native `linux_x86_64` tag; system libraries are not bundled.
- Windows x86-64: Windows 10/11. `SOFFICE` uses the console launcher.
- macOS x86-64 and arm64: macOS 11+.
- No Linux arm64, musl/Alpine, or 32-bit wheels.

Fonts affect layout and are not supplied by lo4py. GUI features need a desktop. Some Base features need Java, which is not bundled. UNO bindings are compiled for LibreOffice's bundled Python, not for yours: `import uno` will not work in your own interpreter, but `extract` and `recalculate` use the bundled one for you. Treat untrusted documents as untrusted code; run conversion in your own restricted worker/container.

LibreOffice inherits the process environment. Java discovery can make startup slow if `PATH` contains network drives or Windows mount paths under WSL; remove those entries in your worker environment if necessary.

On minimal Debian/Ubuntu images, headless conversion needs system libraries:

```sh
apt-get update
apt-get install --no-install-recommends libxinerama1 libcairo2 libcups2 libdbus-1-3 libfontconfig1 libfreetype6 libice6 libsm6 libx11-6 libxext6 libxrender1 libxrandr2 libnss3 libnspr4
```

Optional GTK, Qt, KDE, multimedia, and Java integrations need their corresponding system libraries. The bundled generic GUI and headless converters do not require all desktop toolkits.

## Build and develop

```sh
uv sync --group dev
uv run pytest -m "not integration"
uv run ruff check .
uv run ruff format --check .
uv run mypy

uv run python build_runtime.py
uv run pytest -m integration
uv run python -m build --wheel
uv run python -m build --sdist
```

Wheel builds automatically stage the runtime if it is missing. Editable installs do not download it. Source distributions contain the wrapper and builder, not LibreOffice; building from an sdist needs network access and native extraction tools: `dpkg-deb` on Linux, `msiexec` on Windows, or `hdiutil` on macOS.

Downloads are pinned by SHA-256 and cached in `.cache/lo4py`. `python build_runtime.py --cache PATH` selects another build-time cache. A corrupt cache or mismatched staged runtime is an error, not silently reused.

## Release

The package version is `LibreOffice-major.minor.patch.wrapper-revision`. Start with the latest stable LibreOffice release; older lo4py releases remain available for pinning. There is no historical LibreOffice backfill.

To update LibreOffice, change `src/lo4py/_version.py` (including the upstream build number), the four checksums in `build_runtime.py`, and the corresponding source URL in `NOTICE`. Update the versioned installation examples above.

Push a tag matching the package version:

```sh
git tag v26.8.3.1
git push origin v26.8.3.1
```

The wheel workflow builds and smoke-tests all four supported platforms, then publishes their wheels, the source distribution, and `SHA256SUMS` to a GitHub Release. Publication is gated on every platform passing. A manual workflow run on a branch builds artifacts without publishing. Nothing is uploaded to PyPI.

The wrapper is MIT-licensed. LibreOffice and its bundled components retain their own licenses and notices; see [NOTICE](NOTICE). This project is independent of The Document Foundation.
