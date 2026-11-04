#!/usr/bin/env python3
"""Merge adjacent Word runs that have identical formatting, so visible text is findable.

  python merge_runs.py unpacked/                 # edits the folder in place
  python merge_runs.py in.docx -o merged.docx    # or a packed file

Word splits text into many <w:r> runs (revision ids, spell-check marks, edit
history), so a phrase you can read is often not one string in the XML. This
script joins neighbouring runs whose formatting is the same, removes spell- and
grammar-check markers and run-level revision-id attributes, and leaves the
rendered document unchanged. It processes the body, headers, footers, footnotes
and endnotes.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "office"))
from workspace import opened  # noqa: E402
from xmlutil import W, XML_NS, children, elements, load, remove, save, set_text, text_of  # noqa: E402

RSID = ("w:rsidR", "w:rsidRPr", "w:rsidDel", "w:rsidRDefault")
PARTS = ("document", "header", "footer", "footnotes", "endnotes", "comments")


def signature(run) -> tuple[str, str] | None:
    """(formatting, text element name) when the run holds only plain text, else None."""
    props = None
    kind = None
    for child in children(run):
        if child.namespaceURI != W:
            return None
        if child.localName == "rPr":
            props = child
        elif child.localName in ("t", "delText") and kind in (None, child.localName):
            kind = child.localName
        else:
            return None
    if kind is None:
        return None
    if props is None:
        return "", kind
    clone = props.cloneNode(True)
    for element in [clone, *clone.getElementsByTagName("*")]:
        for attribute in RSID:
            if element.hasAttribute(attribute):
                element.removeAttribute(attribute)
    return clone.toxml(), kind


def merge_in(document, container) -> int:
    merged = 0
    for marker in children(container, W, "proofErr"):
        remove(marker)
    previous, previous_sig = None, None
    for node in list(container.childNodes):
        if node.nodeType == node.TEXT_NODE and not node.data.strip():
            continue
        if node.nodeType != node.ELEMENT_NODE or node.namespaceURI != W or node.localName != "r":
            previous, previous_sig = None, None
            continue
        for attribute in RSID:
            if node.hasAttribute(attribute):
                node.removeAttribute(attribute)
        sig = signature(node)
        if sig is not None and previous is not None and sig == previous_sig:
            target = children(previous, W, sig[1])
            text = "".join(text_of(t) for t in target) + "".join(text_of(t) for t in children(node, W, sig[1]))
            for extra in target[1:]:
                remove(extra)
            set_text(document, target[0], text)
            remove(node)
            merged += 1
            continue
        if sig is not None:
            texts = children(node, W, sig[1])
            if len(texts) > 1:
                joined = "".join(text_of(t) for t in texts)
                for extra in texts[1:]:
                    remove(extra)
                set_text(document, texts[0], joined)
        previous, previous_sig = (node, sig) if sig is not None else (None, None)
    return merged


def process(path: Path) -> int:
    document = load(path)
    total = 0
    containers = elements(document, W, "p")
    for tag in ("ins", "del", "hyperlink", "smartTag", "fldSimple", "sdtContent"):
        containers += elements(document, W, tag)
    for container in containers:
        total += merge_in(document, container)
    save(document, path)
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge identically formatted adjacent runs in a .docx.")
    parser.add_argument("source", help="unpacked folder or .docx")
    parser.add_argument("-o", "--output", help="output .docx (packed input only; default: in place)")
    args = parser.parse_args()
    with opened(args.source, args.output) as folder:
        word = folder / "word"
        files = [p for p in sorted(word.glob("*.xml")) if p.stem.rstrip("0123456789") in PARTS]
        counts = {p.name: process(p) for p in files}
    print(f"merged {sum(counts.values())} runs in " + ", ".join(f"{n} ({c})" for n, c in counts.items() if c)
          if any(counts.values()) else "nothing to merge")
    return 0


if __name__ == "__main__":
    sys.exit(main())
