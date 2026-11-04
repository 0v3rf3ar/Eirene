#!/usr/bin/env python3
"""Print a Word document as Markdown-style text: headings, lists, tables, comments.

  python docx_text.py file.docx [--changes] [--no-comments]

By default tracked changes are shown accepted (insertions in, deletions out).
--changes marks them instead: [+inserted+] and [-deleted-] with the author.
Comments are listed at the end with the text they are attached to. Headers and
footers are included. Uses only Python's standard library, so it works without
pandoc or LibreOffice.
"""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def q(name: str) -> str:
    return f"{{{W}}}{name}"


class Reader:
    def __init__(self, archive: zipfile.ZipFile, changes: bool):
        self.changes = changes
        self.styles = self._styles(archive)
        self.anchors: dict[str, list[str]] = {}
        self.open_comments: set[str] = set()

    @staticmethod
    def _styles(archive: zipfile.ZipFile) -> dict[str, str]:
        if "word/styles.xml" not in archive.namelist():
            return {}
        root = ET.fromstring(archive.read("word/styles.xml"))
        names = {}
        for style in root.iter(q("style")):
            name = style.find(q("name"))
            names[style.get(q("styleId"), "")] = (name.get(q("val")) if name is not None else "") or ""
        return names

    def runs(self, node: ET.Element, inside: str = "") -> str:
        out = []
        for child in node:
            tag = child.tag.rsplit("}", 1)[-1]
            author = child.get(q("author"), "")
            if tag in ("ins", "moveTo"):
                text = self.runs(child, "ins")
                out.append(f"[+{text}+]" if self.changes and text else text)
            elif tag in ("del", "moveFrom"):
                if self.changes:
                    text = self.runs(child, "del")
                    if text:
                        out.append(f"[-{text}-]" + (f"({author})" if author else ""))
            elif tag == "t" or (tag == "delText" and inside == "del"):
                out.append(child.text or "")
                for cid in self.open_comments:
                    self.anchors.setdefault(cid, []).append(child.text or "")
            elif tag == "tab":
                out.append("\t")
            elif tag in ("br", "cr"):
                out.append("\n" if child.get(q("type")) != "page" else "\n\n")
            elif tag == "noBreakHyphen":
                out.append("-")
            elif tag == "commentRangeStart":
                self.open_comments.add(child.get(q("id")))
            elif tag == "commentRangeEnd":
                self.open_comments.discard(child.get(q("id")))
            elif tag in ("r", "hyperlink", "smartTag", "sdt", "sdtContent", "fldSimple", "customXml"):
                out.append(self.runs(child, inside))
        return "".join(out)

    def paragraph(self, p: ET.Element) -> str:
        props = p.find(q("pPr"))
        style = ""
        level = None
        if props is not None:
            style_el = props.find(q("pStyle"))
            if style_el is not None:
                style = self.styles.get(style_el.get(q("val"), ""), style_el.get(q("val"), ""))
            numbering = props.find(q("numPr"))
            if numbering is not None:
                ilvl = numbering.find(q("ilvl"))
                level = int(ilvl.get(q("val"), "0")) if ilvl is not None else 0
        text = self.runs(p).strip("\n")
        if not text.strip():
            return ""
        heading = re.match(r"(?i)heading\s*(\d)", style)
        if heading:
            return "#" * min(6, int(heading.group(1))) + " " + text
        if style.lower() == "title":
            return "# " + text
        if level is not None or style.lower().startswith("list"):
            return "  " * (level or 0) + "- " + text
        return text

    def table(self, tbl: ET.Element) -> str:
        rows = []
        for tr in tbl.findall(q("tr")):
            cells = []
            for tc in tr.findall(q("tc")):
                parts = [self.paragraph(p) for p in tc.iter(q("p"))]
                cells.append(" ".join(part for part in parts if part).replace("|", "\\|").replace("\n", " "))
            rows.append(cells)
        if not rows:
            return ""
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width]
        lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
        return "\n".join(lines)

    def body(self, root: ET.Element) -> list[str]:
        blocks = []
        container = root.find(q("body"))
        container = root if container is None else container
        for child in container:
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "p":
                blocks.append(self.paragraph(child))
            elif tag == "tbl":
                blocks.append(self.table(child))
            elif tag == "sdt":
                content = child.find(q("sdtContent"))
                if content is not None:
                    blocks += self.body(content)
        return [b for b in blocks if b]


def main() -> int:
    parser = argparse.ArgumentParser(description="Word document to Markdown-style text.")
    parser.add_argument("docx")
    parser.add_argument("--changes", action="store_true", help="mark tracked insertions and deletions")
    parser.add_argument("--no-comments", action="store_true")
    args = parser.parse_args()
    with zipfile.ZipFile(args.docx) as archive:
        names = archive.namelist()
        reader = Reader(archive, args.changes)
        for part in sorted(n for n in names if re.fullmatch(r"word/header\d*\.xml", n)):
            text = "\n".join(reader.body(ET.fromstring(archive.read(part))))
            if text.strip():
                print(f"<!-- header: {text.strip()} -->")
        print("\n\n".join(reader.body(ET.fromstring(archive.read("word/document.xml")))))
        for part in sorted(n for n in names if re.fullmatch(r"word/footer\d*\.xml", n)):
            text = "\n".join(reader.body(ET.fromstring(archive.read(part))))
            if text.strip():
                print(f"\n<!-- footer: {text.strip()} -->")
        if not args.no_comments and "word/comments.xml" in names:
            comments = ET.fromstring(archive.read("word/comments.xml"))
            listed = []
            for comment in comments.findall(q("comment")):
                cid = comment.get(q("id"))
                body = " ".join(reader.runs(p) for p in comment.iter(q("p"))).strip()
                anchor = "".join(reader.anchors.get(cid, [])).strip()
                listed.append(f"- [{cid}] {comment.get(q('author'), '')}: {body}"
                              + (f"  (on: \"{anchor[:80]}\")" if anchor else ""))
            if listed:
                print("\n## Comments\n\n" + "\n".join(listed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
