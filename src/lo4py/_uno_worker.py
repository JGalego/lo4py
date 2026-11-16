"""Worker executed by LibreOffice's bundled Python (not the host interpreter).

It must stay standard-library-only apart from ``uno``, and must not import
anything from ``lo4py``. The request arrives as JSON on stdin and the result
leaves as a single JSON document on stdout.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
import traceback
import uuid
from typing import Any

SPREADSHEET = "com.sun.star.sheet.SpreadsheetDocument"
TEXT = "com.sun.star.text.TextDocument"
PRESENTATION = "com.sun.star.presentation.PresentationDocument"
DRAWING = "com.sun.star.drawing.DrawingDocument"

FILTERS = {
    ".xlsx": "Calc MS Excel 2007 XML",
    ".xls": "MS Excel 97",
    ".ods": "calc8",
}


def kill_tree(process: subprocess.Popen[bytes]) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
    else:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)


def fail(message: str) -> None:
    sys.stdout.write(json.dumps({"ok": False, "error": message}))
    sys.stdout.flush()


def property_value(name: str, value: Any) -> Any:
    from com.sun.star.beans import PropertyValue  # type: ignore[import-not-found]

    item = PropertyValue()
    item.Name = name
    item.Value = value
    return item


def connect(
    uno: Any, process: subprocess.Popen[bytes], pipe: str, deadline: float
) -> Any:
    local = uno.getComponentContext()
    resolver = local.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver", local
    )
    url = f"uno:pipe,name={pipe};urp;StarOffice.ComponentContext"
    while True:
        try:
            return resolver.resolve(url)
        except Exception:
            # A launcher may exit cleanly after handing off to the real process.
            if process.poll() not in (None, 0):
                raise RuntimeError(
                    f"LibreOffice exited with status {process.returncode} "
                    "before accepting a connection"
                ) from None
            if time.monotonic() > deadline:
                raise TimeoutError("LibreOffice did not accept a connection") from None
            time.sleep(0.1)


def sheet_values(sheet: Any) -> list[list[Any]]:
    cursor = sheet.createCursor()
    cursor.gotoEndOfUsedArea(False)
    address = cursor.getRangeAddress()
    rows = sheet.getCellRangeByPosition(
        0, 0, address.EndColumn, address.EndRow
    ).getDataArray()
    values = [list(row) for row in rows]
    return [] if values == [[""]] else values


def text_content(document: Any) -> str:
    parts: list[str] = []
    paragraphs = document.getText().createEnumeration()
    while paragraphs.hasMoreElements():
        element = paragraphs.nextElement()
        if element.supportsService("com.sun.star.text.Paragraph"):
            parts.append(element.getString())
        elif element.supportsService("com.sun.star.text.TextTable"):
            parts.extend(
                "\t".join(str(cell) for cell in row) for row in element.getDataArray()
            )
    return "\n".join(parts)


def shapes_text(document: Any) -> str:
    pages = document.getDrawPages()
    slides: list[str] = []
    for index in range(pages.getCount()):
        page = pages.getByIndex(index)
        strings = []
        for position in range(page.getCount()):
            shape = page.getByIndex(position)
            if hasattr(shape, "getString") and shape.getString():
                strings.append(shape.getString())
        slides.append("\n".join(strings))
    return "\n\n".join(slides)


def extract(document: Any, recalculate: bool) -> dict[str, Any]:
    if document.supportsService(SPREADSHEET):
        if recalculate:
            document.calculateAll()
        sheets = document.getSheets()
        values = {
            name: sheet_values(sheets.getByName(name))
            for name in sheets.getElementNames()
        }
        text = "\n".join(
            "\t".join("" if cell == "" else str(cell) for cell in row)
            for rows in values.values()
            for row in rows
        )
        return {"kind": "spreadsheet", "text": text, "sheets": values}
    if document.supportsService(TEXT):
        return {"kind": "text", "text": text_content(document), "sheets": {}}
    if document.supportsService(PRESENTATION):
        return {"kind": "presentation", "text": shapes_text(document), "sheets": {}}
    if document.supportsService(DRAWING):
        return {"kind": "drawing", "text": shapes_text(document), "sheets": {}}
    raise ValueError("Unsupported document type")


def perform(request: dict[str, Any], desktop: Any, uno: Any) -> dict[str, Any]:
    operation = request["operation"]
    saving = operation == "recalculate"
    properties = [
        property_value("Hidden", True),
        property_value("MacroExecutionMode", 0),  # NEVER_EXECUTE
        property_value("UpdateDocMode", 0),  # NO_UPDATE
        property_value("ReadOnly", not saving),
    ]
    document = desktop.loadComponentFromURL(
        uno.systemPathToFileUrl(request["source"]), "_blank", 0, tuple(properties)
    )
    if document is None:
        raise ValueError("LibreOffice could not open the document")
    try:
        if operation == "extract":
            return {"ok": True, **extract(document, request["recalculate"])}
        if not document.supportsService(SPREADSHEET):
            raise ValueError("Only spreadsheets can be recalculated")
        document.calculateAll()
        suffix = request["suffix"]
        document.storeToURL(
            uno.systemPathToFileUrl(request["output"]),
            (property_value("FilterName", FILTERS[suffix]),),
        )
        return {"ok": True}
    finally:
        document.close(True)


def main() -> int:
    request = json.load(sys.stdin)
    program = request["program"]
    if sys.platform == "win32":
        os.add_dll_directory(program)
    sys.path.insert(0, program)
    import uno  # type: ignore[import-not-found]

    deadline = time.monotonic() + request["timeout"]
    pipe = f"lo4py-{uuid.uuid4().hex}"
    process = subprocess.Popen(
        [
            request["soffice"],
            f"-env:UserInstallation={request['profile']}",
            "--headless",
            "--norestore",
            "--nologo",
            "--nodefault",
            "--nolockcheck",
            f"--accept=pipe,name={pipe};urp;",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=os.name != "nt",
    )

    def expire() -> None:
        kill_tree(process)
        fail("Timed out waiting for LibreOffice")
        os._exit(2)

    watchdog = threading.Timer(max(request["timeout"], 1), expire)
    watchdog.daemon = True
    watchdog.start()
    code = 0
    try:
        context = connect(uno, process, pipe, deadline)
        desktop = context.ServiceManager.createInstanceWithContext(
            "com.sun.star.frame.Desktop", context
        )
        try:
            result = perform(request, desktop, uno)
        finally:
            with contextlib.suppress(Exception):
                desktop.terminate()
        sys.stdout.write(json.dumps(result))
    except Exception as error:
        code = 1
        detail = traceback.format_exc(limit=3) if os.environ.get("LO4PY_DEBUG") else ""
        fail(f"{type(error).__name__}: {error}" + (f"\n{detail}" if detail else ""))
    finally:
        watchdog.cancel()
        if code == 0:
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=10)
        kill_tree(process)
    sys.stdout.flush()
    return code


if __name__ == "__main__":
    sys.exit(main())
