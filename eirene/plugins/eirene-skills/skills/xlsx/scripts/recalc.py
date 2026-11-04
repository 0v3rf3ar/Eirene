#!/usr/bin/env python3
"""Recalculate every formula in a workbook with LibreOffice, then report errors.

  python recalc.py book.xlsx [timeout_seconds] [--force]

openpyxl and most generators write formulas without results, so anything that
reads cached values (pandas, openpyxl data_only=True, previews) sees None. This
opens the workbook in LibreOffice, recalculates all formulas, saves it in place,
and prints JSON:

  {"status": "success" | "errors_found", "total_formulas": N, "total_errors": N,
   "error_summary": {"#DIV/0!": {"count": N, "locations": ["Sheet1!B4", ...]}},
   "locations_truncated": N}

Up to 100 locations are listed per error type; trust total_errors. If the
recalculation itself fails you get {"error": "..."} and exit status 1; otherwise
the exit status is 0 even when errors_found — read the status.

Workbooks with links to other files are refused: LibreOffice cannot open the
linked files, writes #NAME? and drops the links. --force recalculates anyway and
accepts that loss.
"""

from __future__ import annotations

import json
import posixpath
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "office"))
from soffice import run  # noqa: E402

X = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
LIMIT = 100

MACRO = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE script:module PUBLIC "-//OpenOffice.org//DTD OfficeDocument 1.0//EN" "module.dtd">
<script:module xmlns:script="http://openoffice.org/2000/script" script:name="Module1" script:language="StarBasic">
Sub Recalc(url As String)
    Dim args(0) As New com.sun.star.beans.PropertyValue
    args(0).Name = "Hidden"
    args(0).Value = True
    Dim doc As Object
    doc = StarDesktop.loadComponentFromURL(url, "_blank", 0, args())
    doc.calculateAll()
    doc.store()
    doc.close(True)
End Sub
</script:module>
"""
LIBRARY = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE library:library PUBLIC "-//OpenOffice.org//DTD OfficeDocument 1.0//EN" "library.dtd">
<library:library xmlns:library="http://openoffice.org/2000/library" library:name="Standard" library:readonly="false" library:passwordprotected="false">
 <library:element library:name="Module1"/>
</library:library>
"""
DIALOGS = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE library:library PUBLIC "-//OpenOffice.org//DTD OfficeDocument 1.0//EN" "library.dtd">
<library:library xmlns:library="http://openoffice.org/2000/library" library:name="Standard" library:readonly="false" library:passwordprotected="false"/>
"""
CONTAINER = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE library:libraries PUBLIC "-//OpenOffice.org//DTD OfficeDocument 1.0//EN" "libraries.dtd">
<library:libraries xmlns:library="http://openoffice.org/2000/library" xmlns:xlink="http://www.w3.org/1999/xlink">
 <library:library library:name="Standard" xlink:href="$(USER)/basic/Standard/{name}.xlb/" xlink:type="simple" library:link="false"/>
</library:libraries>
"""


def profile_with_macro(timeout: float) -> Path:
    """A fresh LibreOffice profile holding the Recalc macro.

    LibreOffice ignores macro files in a profile it has not initialised yet, so
    start it once to create the profile, then add the macro library.
    """
    profile = Path(tempfile.mkdtemp(prefix="recalc-profile-"))
    run(["--terminate_after_init"], timeout=timeout, profile=profile)
    basic = profile / "user" / "basic"
    (basic / "Standard").mkdir(parents=True, exist_ok=True)
    (basic / "Standard" / "Module1.xba").write_text(MACRO, encoding="utf-8")
    (basic / "Standard" / "script.xlb").write_text(LIBRARY, encoding="utf-8")
    (basic / "Standard" / "dialog.xlb").write_text(DIALOGS, encoding="utf-8")
    (basic / "script.xlc").write_text(CONTAINER.format(name="script"), encoding="utf-8")
    (basic / "dialog.xlc").write_text(CONTAINER.format(name="dialog"), encoding="utf-8")
    return profile


def sheet_names(archive: zipfile.ZipFile) -> dict[str, str]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {r.get("Id"): r.get("Target") for r in rels.findall(f"{{{REL}}}Relationship")}
    names = {}
    for sheet in workbook.iter(f"{{{X}}}sheet"):
        target = targets.get(sheet.get(f"{{{R}}}id"), "")
        part = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
        names[part] = sheet.get("name")
    return names


def scan(path: Path) -> dict:
    formulas, errors, total = 0, {}, 0
    with zipfile.ZipFile(path) as archive:
        for part, name in sheet_names(archive).items():
            if part not in archive.namelist():
                continue
            for _, cell in ET.iterparse(archive.open(part)):
                if cell.tag != f"{{{X}}}c":
                    continue
                if cell.find(f"{{{X}}}f") is not None:
                    formulas += 1
                if cell.get("t") == "e":
                    value = cell.findtext(f"{{{X}}}v") or "#ERROR"
                    total += 1
                    entry = errors.setdefault(value, {"count": 0, "locations": []})
                    entry["count"] += 1
                    if len(entry["locations"]) < LIMIT:
                        sheet = f"'{name}'" if re.search(r"[^A-Za-z0-9_]", name) else name
                        entry["locations"].append(f"{sheet}!{cell.get('r')}")
                cell.clear()
    truncated = sum(e["count"] - len(e["locations"]) for e in errors.values())
    result = {"status": "errors_found" if total else "success", "total_formulas": formulas,
              "total_errors": total, "error_summary": errors}
    if truncated:
        result["locations_truncated"] = truncated
    return result


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--force"]
    force = "--force" in sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    path = Path(args[0]).resolve()
    timeout = float(args[1]) if len(args) > 1 else 30.0
    if not path.exists():
        print(json.dumps({"error": f"{path} does not exist"}))
        return 1
    try:
        with zipfile.ZipFile(path) as archive:
            links = [n for n in archive.namelist() if n.startswith("xl/externalLinks/") and n.endswith(".xml")]
    except zipfile.BadZipFile:
        print(json.dumps({"error": f"{path.name} is not an .xlsx/.xlsm workbook"}))
        return 1
    if links and not force:
        print(json.dumps({"error": f"the workbook links to {len(links)} other file(s); recalculating would replace "
                          "those values with #NAME? and remove the links. Copy the needed values out of the "
                          "original first, or pass --force to accept the loss."}))
        return 1
    try:
        profile = profile_with_macro(timeout + 30)
    except SystemExit as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    backup = path.with_name(path.name + ".recalc-backup")
    shutil.copyfile(path, backup)
    try:
        result = run([f'macro:///Standard.Module1.Recalc("{path.as_uri()}")'], timeout=timeout + 30, profile=profile)
        report = scan(path)
    except (SystemExit, Exception) as exc:  # LibreOffice missing, timed out, or wrote a broken file
        shutil.copyfile(backup, path)
        print(json.dumps({"error": f"recalculation failed: {exc}"}))
        return 1
    finally:
        backup.unlink(missing_ok=True)
        shutil.rmtree(profile, ignore_errors=True)
    if result.returncode:
        print(json.dumps({"error": f"LibreOffice exited with {result.returncode}: {result.stderr.strip()[-500:]}"}))
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
