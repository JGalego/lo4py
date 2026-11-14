# lo4py

LibreOffice shipped in a Python package. No system installation, no first-use download, no Python runtime dependencies.

## Install

```sh
pip install lo4py
```

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
uvx lo4py --version
```

All arguments are passed directly to LibreOffice; the exit status is preserved. Native CLI conversion has LibreOffice's own profile and overwrite behavior. Use the Python `convert` helper for isolated jobs and checked output.

## Platforms and limits

- Python 3.10 or newer.
- Linux x86-64: glibc 2.28+, an x86-64-v2 CPU, and distribution-provided native libraries. Wheels use `linux_x86_64`, not a misleading `manylinux` tag. These wheels can be installed from a file or private index, but cannot be uploaded to PyPI as-is.
- Windows x86-64: Windows 10/11. `SOFFICE` uses the console launcher.
- macOS x86-64 and arm64: macOS 11+.
- No Linux arm64, musl/Alpine, or 32-bit wheels.

Fonts affect layout and are not supplied by lo4py. GUI features need a desktop. Some Base features need Java, which is not bundled. UNO is accessible through LibreOffice's native interfaces, but lo4py does not install Python UNO bindings for the host interpreter. Treat untrusted documents as untrusted code; run conversion in your own restricted worker/container.

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
uv run python -m build
```

Wheel builds automatically stage the runtime if it is missing. Editable installs do not download it. Source distributions contain the wrapper and builder, not LibreOffice; building from an sdist needs network access and native extraction tools: `dpkg-deb` on Linux, `msiexec` on Windows, or `hdiutil` on macOS.

Downloads are pinned by SHA-256 and cached in `.cache/lo4py`. `python build_runtime.py --cache PATH` selects another build-time cache. A corrupt cache or mismatched staged runtime is an error, not silently reused.

The package version is `LibreOffice-major.minor.patch.wrapper-revision`. To update LibreOffice, change `src/lo4py/_version.py` (including the upstream build number), the four checksums in `build_runtime.py`, and the corresponding source URL in `NOTICE`. Native wheel jobs build each platform's wheel and smoke-test an installed copy. They upload workflow artifacts, not PyPI releases.

PyPI publication needs a large-file allowance for the bundled runtime. Portable Linux publication also needs a separately validated manylinux packaging policy; simply relabeling these wheels is not sufficient.

The wrapper is MIT-licensed. LibreOffice and its bundled components retain their own licenses and notices; see [NOTICE](NOTICE). This project is independent of The Document Foundation.
