import subprocess
import sys

from . import run


def main() -> int:
    """Pass command-line arguments directly to LibreOffice."""
    try:
        code = run(sys.argv[1:], check=False).returncode
    except (OSError, subprocess.SubprocessError) as error:
        print(f"lo4py: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return code if code >= 0 else 128 - code


if __name__ == "__main__":
    sys.exit(main())
