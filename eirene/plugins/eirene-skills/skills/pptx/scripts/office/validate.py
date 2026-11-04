#!/usr/bin/env python3
"""Check a .docx, .pptx or .xlsx (packed or unpacked) for structural problems.

  python validate.py FILE [--original SOURCE] [--author NAME] [--json]

Checks every package: XML is well formed; every part has a content type; every
relationship points at a part that exists; every r:id used in a part is defined.
Then format-specific checks:

  docx  tracked-change and comment bookkeeping; with --author (and --original),
        that every text change made under that name is tracked
  pptx  slide list, slide ids, layout links, element order in presentation.xml,
        and chart XML that PowerPoint refuses to open
  xlsx  sheet links, shared-string indexes, formula cells

--original SOURCE reports only problems that SOURCE does not already have, so a
template's own defects are not blamed on your edit. Exit status is 1 when any
error remains, 0 otherwise. Each message says how to fix the problem.
"""

from __future__ import annotations

import argparse
import difflib
import json
import posixpath
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from package import CONTENT_TYPES, read_parts  # noqa: E402

NS = {
    "ct": "http://schemas.openxmlformats.org/package/2006/content-types",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
}
R_ATTRS = ("id", "embed", "link", "pict", "dm", "lo", "qs", "cs")
EXTERNAL = "External"



def q(prefix: str, name: str) -> str:
    return f"{{{NS[prefix]}}}{name}"


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def parse_all(parts: dict[str, bytes], report: Report) -> dict[str, ET.Element]:
    trees = {}
    for name, data in parts.items():
        if not (name.endswith(".xml") or name.endswith(".rels") or name.endswith(".vml")):
            continue
        if b"<!DOCTYPE" in data[:2048] or b"<!ENTITY" in data[:4096]:
            report.error(f"{name}: contains a DOCTYPE/ENTITY declaration; Office XML never does. Remove it.")
            continue
        try:
            trees[name] = ET.fromstring(data)
        except ET.ParseError as exc:
            report.error(f"{name}: not well-formed XML ({exc}). Fix the markup at that line and column.")
    return trees


def rels_path(part: str) -> str:
    folder, name = posixpath.split(part)
    return posixpath.join(folder, "_rels", name + ".rels")


def source_of(rels: str) -> str:
    folder, name = posixpath.split(rels)
    return posixpath.join(posixpath.dirname(folder), name[: -len(".rels")])


def resolve(source: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(posixpath.dirname(source), target))


def relationships(trees: dict[str, ET.Element], part: str) -> dict[str, dict]:
    tree = trees.get(rels_path(part))
    if tree is None:
        return {}
    return {r.get("Id"): {"type": r.get("Type", ""), "target": r.get("Target", ""),
                          "mode": r.get("TargetMode", "")}
            for r in tree.findall(q("rel", "Relationship"))}


def check_package(parts: dict[str, bytes], trees: dict[str, ET.Element], report: Report) -> None:
    if CONTENT_TYPES not in parts:
        report.error(f"{CONTENT_TYPES} is missing; repack from the unpacked folder's root.")
        return
    types = trees.get(CONTENT_TYPES)
    if types is None:
        return
    defaults = {d.get("Extension", "").lower() for d in types.findall(q("ct", "Default"))}
    overrides = {o.get("PartName", "").lstrip("/") for o in types.findall(q("ct", "Override"))}
    for name in parts:
        if name == CONTENT_TYPES or name.endswith("/"):
            continue
        extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if name not in overrides and extension not in defaults:
            report.error(f"{name}: has no content type. Add an <Override PartName=\"/{name}\"> "
                         f"(or a <Default Extension=\"{extension}\">) to {CONTENT_TYPES}.")
    for name in sorted(overrides - set(parts)):
        # Office ignores these, and some generators (pptxgenjs) always write them.
        report.warn(f"{CONTENT_TYPES}: override for /{name}, which does not exist.")

    for rels, tree in trees.items():
        if not rels.endswith(".rels"):
            continue
        source = source_of(rels)
        if source and source not in parts:
            report.warn(f"{rels}: relationships for {source}, which does not exist; delete the .rels file.")
        seen = set()
        for r in tree.findall(q("rel", "Relationship")):
            rid, target = r.get("Id"), r.get("Target", "")
            if rid in seen:
                report.error(f"{rels}: relationship id {rid} is used twice. Give each relationship its own Id.")
            seen.add(rid)
            if r.get("TargetMode") == EXTERNAL or re.match(r"^[a-z]+:", target):
                continue
            resolved = resolve(source or "x", target) if source else target.lstrip("/")
            if resolved not in parts:
                report.error(f"{rels}: {rid} points to {resolved}, which does not exist. "
                             f"Restore that part or remove the relationship and every reference to {rid}.")

    for name, tree in trees.items():
        if name.endswith(".rels") or name == CONTENT_TYPES:
            continue
        defined = relationships(trees, name)
        for element in tree.iter():
            for attribute in R_ATTRS:
                value = element.get(q("r", attribute))
                if value and value not in defined:
                    report.error(f"{name}: <{local(element.tag)} r:{attribute}=\"{value}\"> has no matching "
                                 f"relationship in {rels_path(name)}. Add it, or use an existing id.")


# docx ---------------------------------------------------------------------------

def check_docx(parts: dict[str, bytes], trees: dict[str, ET.Element], report: Report) -> None:
    document = trees.get("word/document.xml")
    if document is None:
        report.error("word/document.xml is missing or unreadable.")
        return
    ids: dict[str, str] = {}
    for kind in ("ins", "del", "moveFrom", "moveTo"):
        for element in document.iter(q("w", kind)):
            wid = element.get(q("w", "id"))
            if wid is None:
                report.error(f"word/document.xml: <w:{kind}> without w:id. Add a unique w:id.")
            elif wid in ids and element.tag != ids[wid]:
                report.error(f"word/document.xml: revision id {wid} is used by more than one change. "
                             "Give each <w:ins>/<w:del> its own w:id.")
            else:
                ids[wid] = element.tag
            if element.get(q("w", "author")) is None:
                report.warn(f"word/document.xml: <w:{kind} w:id=\"{wid}\"> has no w:author.")
    for deleted in document.iter(q("w", "del")):
        for text in deleted.iter(q("w", "t")):
            report.error("word/document.xml: <w:t> inside <w:del>; deleted text must be <w:delText>.")
            break
    for inserted in document.iter(q("w", "ins")):
        for text in inserted.iter(q("w", "delText")):
            report.error("word/document.xml: <w:delText> inside <w:ins>; inserted text must be <w:t>.")
            break
    for text in document.iter(q("w", "t")):
        value = text.text or ""
        if value != value.strip() and text.get("{http://www.w3.org/XML/1998/namespace}space") != "preserve":
            report.warn("word/document.xml: text with leading/trailing spaces lacks xml:space=\"preserve\"; "
                        "Word will drop the spaces.")
            break

    comments = trees.get("word/comments.xml")
    known = {c.get(q("w", "id")) for c in comments.iter(q("w", "comment"))} if comments is not None else set()
    starts = {e.get(q("w", "id")) for e in document.iter(q("w", "commentRangeStart"))}
    ends = {e.get(q("w", "id")) for e in document.iter(q("w", "commentRangeEnd"))}
    refs = {e.get(q("w", "id")) for e in document.iter(q("w", "commentReference"))}
    for cid in sorted((starts | ends | refs) - known):
        report.error(f"word/document.xml: comment marker for id {cid}, but word/comments.xml has no such comment.")
    for cid in sorted(starts ^ ends):
        report.error(f"word/document.xml: comment {cid} has a range start or end without the other.")
    for cid in sorted(known - refs):
        report.warn(f"comment {cid} has no <w:commentReference> in the document, so it will not show.")


def paragraph_texts(document: ET.Element, *, revert_author: str | None = None) -> list[str]:
    """Visible text per paragraph; with revert_author, as if that author's changes were rejected."""
    result = []
    for paragraph in document.iter(q("w", "p")):
        pieces = []

        def walk(node: ET.Element, inside_del: bool, inside_ins: bool) -> None:
            tag = local(node.tag)
            author = node.get(q("w", "author"))
            mine = revert_author is not None and author == revert_author
            if tag == "p" and node is not paragraph:
                return  # nested paragraphs (text boxes) are visited on their own
            if tag == "ins" and mine:
                return  # rejecting an insertion removes it
            if tag == "del":
                inside_del = not mine  # rejecting a deletion restores the text
            if tag == "t" and not inside_del:
                pieces.append(node.text or "")
            elif tag == "delText" and not inside_del:
                pieces.append(node.text or "")
            elif tag == "tab":
                pieces.append("\t")
            for child in node:
                walk(child, inside_del, inside_ins)

        walk(paragraph, False, False)
        result.append("".join(pieces))
    return result


def check_redlines(original: dict[str, bytes], parts: dict[str, bytes], author: str, report: Report) -> None:
    try:
        before = ET.fromstring(original["word/document.xml"])
        after = ET.fromstring(parts["word/document.xml"])
    except (KeyError, ET.ParseError):
        report.error("--author: cannot read word/document.xml in both files.")
        return
    old = [t for t in paragraph_texts(before) if t.strip()]
    new = [t for t in paragraph_texts(after, revert_author=author) if t.strip()]
    if old == new:
        return
    diff = list(difflib.unified_diff(old, new, "original", f"edited, {author}'s changes rejected", n=0, lineterm=""))
    shown = "\n      ".join(line[:160] for line in diff[2:14])
    report.error(f"untracked edits: rejecting every change by {author!r} does not give back the original text. "
                 f"Wrap these edits in <w:ins>/<w:del w:author=\"{author}\">:\n      {shown}")


# pptx ---------------------------------------------------------------------------

def check_pptx(parts: dict[str, bytes], trees: dict[str, ET.Element], report: Report) -> None:
    presentation = trees.get("ppt/presentation.xml")
    if presentation is None:
        report.error("ppt/presentation.xml is missing or unreadable.")
        return
    # Element order is not checked: PowerPoint accepts the order pptxgenjs writes
    # (notesMasterIdLst after sldIdLst) and moving elements can break a deck.
    first = next(iter(presentation), None)
    if first is not None and local(first.tag) != "sldMasterIdLst":
        report.error("ppt/presentation.xml: <p:sldMasterIdLst> must be the first child of <p:presentation>.")
    rels = relationships(trees, "ppt/presentation.xml")
    seen_ids, seen_rids = set(), set()
    slide_list = presentation.find(q("p", "sldIdLst"))
    for entry in slide_list if slide_list is not None else []:
        sid, rid = entry.get("id"), entry.get(q("r", "id"))
        if sid is None or not sid.isdigit() or not 256 <= int(sid) < 2147483648:
            report.error(f"ppt/presentation.xml: slide id {sid!r} must be a number from 256 to 2147483647.")
        if sid in seen_ids:
            report.error(f"ppt/presentation.xml: slide id {sid} appears twice in <p:sldIdLst>.")
        if rid in seen_rids:
            report.error(f"ppt/presentation.xml: {rid} is listed twice in <p:sldIdLst>.")
        seen_ids.add(sid)
        seen_rids.add(rid)
        if rid in rels and not rels[rid]["type"].endswith("/slide"):
            report.error(f"ppt/presentation.xml: {rid} in <p:sldIdLst> is not a slide relationship.")
    listed = {resolve("ppt/presentation.xml", rels[r]["target"]) for r in seen_rids if r in rels}
    for name in sorted(parts):
        if re.fullmatch(r"ppt/slides/slide\d+\.xml", name):
            if name not in listed:
                report.warn(f"{name} is not in <p:sldIdLst>, so it is hidden; run clean.py to remove it.")
            slide_rels = relationships(trees, name)
            if not any(r["type"].endswith("/slideLayout") for r in slide_rels.values()):
                report.error(f"{name}: has no slideLayout relationship. Every slide needs one.")
            check_slide(name, trees.get(name), report)
    for name, tree in trees.items():
        if re.fullmatch(r"ppt/charts/chart\d+\.xml", name):
            check_chart(name, tree, report)


def check_slide(name: str, tree: ET.Element | None, report: Report) -> None:
    if tree is None:
        return
    ids = {}
    for element in tree.iter(q("p", "cNvPr")):
        sid = element.get("id")
        if sid in ids:
            report.warn(f"{name}: shape id {sid} is used by more than one shape; give each a unique id.")
        ids[sid] = True
    for paragraph in tree.iter(q("a", "p")):
        children = [local(c.tag) for c in paragraph]
        if "pPr" in children and children.index("pPr") != 0:
            report.error(f"{name}: <a:pPr> must be the first child of <a:p>.")
        if "endParaRPr" in children and children[-1] != "endParaRPr":
            report.error(f"{name}: <a:endParaRPr> must be the last child of <a:p>.")
    for text in tree.iter(q("a", "t")):
        if "•" in (text.text or "")[:2]:
            report.warn(f"{name}: text starts with a literal bullet character; use paragraph bullets instead.")
            break


def check_chart(name: str, tree: ET.Element, report: Report) -> None:
    plot = tree.find(f".//{q('c', 'plotArea')}")
    if plot is None:
        return
    declared = set()
    for axis in ("catAx", "valAx", "dateAx", "serAx"):
        for element in plot.findall(q("c", axis)):
            axid = element.find(q("c", "axId"))
            if axid is not None:
                declared.add(axid.get("val"))
    for group in plot:
        kind = local(group.tag)
        if not kind.endswith("Chart"):
            continue
        # 2-D charts carry a spare third axId slot that need not be declared.
        axes = group.findall(q("c", "axId"))
        if "3D" not in kind:
            axes = axes[:2]
        for axid in axes:
            if axid.get("val") not in declared:
                report.error(f"{name}: {kind} uses axis id {axid.get('val')}, which no axis declares; PowerPoint "
                             "drops the chart. For secondary axes give the chart both valAxes and catAxes "
                             "(two entries each) in the generator.")
        grouping = group.find(q("c", "grouping"))
        if kind == "barChart" and grouping is not None and grouping.get("val") in ("stacked", "percentStacked"):
            for position in group.iter(q("c", "dLblPos")):
                if position.get("val") == "outEnd":
                    report.error(f"{name}: stacked bar chart with data labels at outEnd, which PowerPoint "
                                 "rejects. Use ctr, inEnd or inBase.")
                    break


# xlsx ---------------------------------------------------------------------------

def check_xlsx(parts: dict[str, bytes], trees: dict[str, ET.Element], report: Report) -> None:
    workbook = trees.get("xl/workbook.xml")
    if workbook is None:
        report.error("xl/workbook.xml is missing or unreadable.")
        return
    rels = relationships(trees, "xl/workbook.xml")
    names = set()
    for sheet in workbook.iter(q("x", "sheet")):
        title, rid = sheet.get("name", ""), sheet.get(q("r", "id"))
        if title.casefold() in names:
            report.error(f"xl/workbook.xml: two sheets are named {title!r}; sheet names must be unique.")
        names.add(title.casefold())
        if len(title) > 31 or re.search(r"[\\/?*\[\]:]", title):
            report.error(f"xl/workbook.xml: sheet name {title!r} is over 31 characters or uses \\ / ? * [ ] :.")
        if rid not in rels:
            report.error(f"xl/workbook.xml: sheet {title!r} points to {rid}, which is not defined.")
    strings = trees.get("xl/sharedStrings.xml")
    count = len(strings.findall(q("x", "si"))) if strings is not None else 0
    for name, tree in trees.items():
        if not re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name):
            continue
        for cell in tree.iter(q("x", "c")):
            if cell.get("t") == "s":
                value = cell.find(q("x", "v"))
                if value is not None and value.text and value.text.isdigit() and int(value.text) >= count:
                    report.error(f"{name}: cell {cell.get('r')} refers to shared string {value.text}, "
                                 f"but there are only {count}.")


# main ---------------------------------------------------------------------------

def kind_of(parts: dict[str, bytes]) -> str:
    if "word/document.xml" in parts:
        return "docx"
    if "ppt/presentation.xml" in parts:
        return "pptx"
    if "xl/workbook.xml" in parts:
        return "xlsx"
    return "unknown"


def validate(path: str | Path) -> tuple[str, Report, dict[str, bytes]]:
    report = Report()
    try:
        parts = read_parts(path)
    except Exception as exc:  # bad zip, unreadable folder
        report.error(f"cannot open {path}: {exc}")
        return "unknown", report, {}
    trees = parse_all(parts, report)
    check_package(parts, trees, report)
    kind = kind_of(parts)
    {"docx": check_docx, "pptx": check_pptx, "xlsx": check_xlsx}.get(kind, lambda *a: None)(parts, trees, report)
    return kind, report, parts


def main() -> int:
    parser = argparse.ArgumentParser(description="Structural checks for Office files.")
    parser.add_argument("file", help=".docx/.pptx/.xlsx file or an unpacked folder")
    parser.add_argument("--original", help="the file this one was made from; its own problems are not reported")
    parser.add_argument("--author", help="docx: check that every change by this author is tracked (needs --original)")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args()

    kind, report, parts = validate(args.file)
    suppressed = 0
    original_parts: dict[str, bytes] = {}
    if args.original:
        _, baseline, original_parts = validate(args.original)
        known = set(baseline.errors) | set(baseline.warnings)
        before = len(report.errors) + len(report.warnings)
        report.errors = [e for e in report.errors if e not in known]
        report.warnings = [w for w in report.warnings if w not in known]
        suppressed = before - len(report.errors) - len(report.warnings)
    if args.author:
        if kind != "docx" or not original_parts:
            report.error("--author needs a .docx and --original.")
        else:
            check_redlines(original_parts, parts, args.author, report)

    if args.json:
        print(json.dumps({"file": str(args.file), "type": kind, "ok": not report.errors,
                          "errors": report.errors, "warnings": report.warnings,
                          "suppressed_from_original": suppressed}, indent=2))
    else:
        for line in report.errors:
            print(f"error: {line}")
        for line in report.warnings:
            print(f"warning: {line}")
        note = f" ({suppressed} already in the original)" if suppressed else ""
        print(f"{args.file}: {kind}, {len(report.errors)} errors, {len(report.warnings)} warnings{note}")
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
