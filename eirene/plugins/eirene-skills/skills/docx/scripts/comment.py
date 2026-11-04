#!/usr/bin/env python3
"""Add a comment (or a reply) to a Word document.

  python comment.py unpacked/ "The cap looks too low" --anchor "fees are capped at"
  python comment.py unpacked/ "Agreed" --parent 0
  python comment.py contract.docx "Check this date" --anchor "1 March" -o reviewed.docx

Creates or updates comments.xml, commentsExtended.xml, commentsIds.xml and
commentsExtensible.xml, their relationships and content types, and prints the
new comment's id.

--anchor TEXT places the comment on the first occurrence of TEXT in the body
(run merge_runs.py first so the text is in one run). Without --anchor the script
prints the markers to paste around the text yourself; until they are in
word/document.xml the comment exists but does not show. A reply (--parent ID)
is placed on its parent's range automatically.
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "office"))
import relations  # noqa: E402
from workspace import opened  # noqa: E402
from xmlutil import W, children, elements, first, load, save, set_text, text_of  # noqa: E402

import xml.dom.minidom as minidom

W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
W15 = "http://schemas.microsoft.com/office/word/2012/wordml"
W16CID = "http://schemas.microsoft.com/office/word/2016/wordml/cid"
W16CEX = "http://schemas.microsoft.com/office/word/2018/wordml/cex"
OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
CT_BASE = "application/vnd.openxmlformats-officedocument.wordprocessingml."
PARTS = {
    "comments": (f"{OFFICE_REL}/comments", f"<w:comments xmlns:w=\"{W}\" xmlns:w14=\"{W14}\"/>"),
    "commentsExtended": ("http://schemas.microsoft.com/office/2011/relationships/commentsExtended",
                         f"<w15:commentsEx xmlns:w15=\"{W15}\"/>"),
    "commentsIds": ("http://schemas.microsoft.com/office/2016/09/relationships/commentsIds",
                    f"<w16cid:commentsIds xmlns:w16cid=\"{W16CID}\"/>"),
    "commentsExtensible": ("http://schemas.microsoft.com/office/2018/08/relationships/commentsExtensible",
                           f"<w16cex:commentsExtensible xmlns:w16cex=\"{W16CEX}\"/>"),
}


def hex_id(used: set[str]) -> str:
    while True:
        value = f"{random.randint(1, 0x7FFFFFFE):08X}"
        if value not in used:
            used.add(value)
            return value


def part(folder: Path, name: str) -> tuple[Path, minidom.Document]:
    path = folder / "word" / f"{name}.xml"
    rel_type, empty = PARTS[name]
    if path.exists():
        document = load(path)
    else:
        document = minidom.parseString(empty.encode())
    relations.add(folder, "word/document.xml", rel_type, f"word/{name}.xml")
    relations.set_override(folder, f"word/{name}.xml", f"{CT_BASE}{name}+xml")
    return path, document


def initials(author: str) -> str:
    return "".join(word[0] for word in author.split()[:3]).upper() or "A"


def add_comment(folder: Path, text: str, author: str, parent: str | None) -> tuple[str, str]:
    stamp = datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    comments_path, comments = part(folder, "comments")
    existing = elements(comments, W, "comment")
    ids = [int(c.getAttributeNS(W, "id")) for c in existing if c.getAttributeNS(W, "id").isdigit()]
    new_id = str(max(ids, default=-1) + 1)
    para_ids: set[str] = set()
    for p in elements(comments, W, "p"):
        if p.getAttributeNS(W14, "paraId"):
            para_ids.add(p.getAttributeNS(W14, "paraId"))
    parent_para = None
    if parent is not None:
        match = [c for c in existing if c.getAttributeNS(W, "id") == parent]
        if not match:
            raise SystemExit(f"no comment with id {parent}")
        paragraphs = elements(match[0], W, "p")
        parent_para = paragraphs[-1].getAttributeNS(W14, "paraId") if paragraphs else None
        if not parent_para:
            raise SystemExit(f"comment {parent} has no paragraph id, so replies cannot be threaded to it")

    root = comments.documentElement
    w = root.prefix or "w"
    w14 = None
    for index in range(root.attributes.length):
        attribute = root.attributes.item(index)
        if attribute.value == W14 and attribute.name.startswith("xmlns:"):
            w14 = attribute.name[6:]
    if w14 is None:
        root.setAttribute("xmlns:w14", W14)
        w14 = "w14"
    para_id = hex_id(para_ids)
    comment = comments.createElementNS(W, f"{w}:comment")
    comment.setAttributeNS(W, f"{w}:id", new_id)
    comment.setAttributeNS(W, f"{w}:author", author)
    comment.setAttributeNS(W, f"{w}:date", stamp)
    comment.setAttributeNS(W, f"{w}:initials", initials(author))
    lines = text.split("\n")
    for number, line in enumerate(lines):
        paragraph = comments.createElementNS(W, f"{w}:p")
        if number == len(lines) - 1:
            paragraph.setAttributeNS(W14, f"{w14}:paraId", para_id)
            paragraph.setAttributeNS(W14, f"{w14}:textId", "77777777")
        else:
            paragraph.setAttributeNS(W14, f"{w14}:paraId", hex_id(para_ids))
        if number == 0:
            ref = comments.createElementNS(W, f"{w}:r")
            ref.appendChild(comments.createElementNS(W, f"{w}:annotationRef"))
            paragraph.appendChild(ref)
        run = comments.createElementNS(W, f"{w}:r")
        t = comments.createElementNS(W, f"{w}:t")
        set_text(comments, t, line)
        run.appendChild(t)
        paragraph.appendChild(run)
        comment.appendChild(paragraph)
    root.appendChild(comment)
    save(comments, comments_path)

    durable = hex_id(set())
    path, extended = part(folder, "commentsExtended")
    entry = extended.createElementNS(W15, "w15:commentEx")
    entry.setAttributeNS(W15, "w15:paraId", para_id)
    if parent_para:
        entry.setAttributeNS(W15, "w15:paraIdParent", parent_para)
    entry.setAttributeNS(W15, "w15:done", "0")
    extended.documentElement.appendChild(entry)
    save(extended, path)

    path, ids_part = part(folder, "commentsIds")
    entry = ids_part.createElementNS(W16CID, "w16cid:commentId")
    entry.setAttributeNS(W16CID, "w16cid:paraId", para_id)
    entry.setAttributeNS(W16CID, "w16cid:durableId", durable)
    ids_part.documentElement.appendChild(entry)
    save(ids_part, path)

    path, extensible = part(folder, "commentsExtensible")
    entry = extensible.createElementNS(W16CEX, "w16cex:commentExtensible")
    entry.setAttributeNS(W16CEX, "w16cex:durableId", durable)
    entry.setAttributeNS(W16CEX, "w16cex:dateUtc", stamp)
    extensible.documentElement.appendChild(entry)
    save(extensible, path)
    return new_id, para_id


def marker(document, name: str, cid: str):
    element = document.createElementNS(W, f"w:{name}")
    element.setAttributeNS(W, "w:id", cid)
    return element


def reference_run(document, cid: str):
    run = document.createElementNS(W, "w:r")
    props = document.createElementNS(W, "w:rPr")
    style = document.createElementNS(W, "w:rStyle")
    style.setAttributeNS(W, "w:val", "CommentReference")
    props.appendChild(style)
    run.appendChild(props)
    run.appendChild(marker(document, "commentReference", cid))
    return run


def anchor_text(document, cid: str, needle: str) -> bool:
    for t in elements(document, W, "t"):
        value = text_of(t)
        position = value.find(needle)
        run = t.parentNode
        if position < 0 or run.localName != "r" or run.parentNode.localName not in ("p", "hyperlink", "ins"):
            continue
        before, match, after = value[:position], value[position:position + len(needle)], value[position + len(needle):]
        container = run.parentNode
        pieces = []
        for piece in (before, match, after):
            clone = run.cloneNode(True)
            texts = children(clone, W, "t")
            for extra in texts[1:]:
                clone.removeChild(extra)
            set_text(document, texts[0], piece)
            pieces.append(clone if piece else None)
        insert_at = run.nextSibling
        container.removeChild(run)
        sequence = []
        if pieces[0] is not None:
            sequence.append(pieces[0])
        sequence += [marker(document, "commentRangeStart", cid), pieces[1],
                     marker(document, "commentRangeEnd", cid), reference_run(document, cid)]
        if pieces[2] is not None:
            sequence.append(pieces[2])
        for node in sequence:
            container.insertBefore(node, insert_at)
        return True
    return False


def anchor_reply(document, cid: str, parent: str) -> bool:
    starts = [e for e in elements(document, W, "commentRangeStart") if e.getAttributeNS(W, "id") == parent]
    ends = [e for e in elements(document, W, "commentRangeEnd") if e.getAttributeNS(W, "id") == parent]
    refs = [e for e in elements(document, W, "commentReference") if e.getAttributeNS(W, "id") == parent]
    if not (starts and ends and refs):
        return False
    starts[0].parentNode.insertBefore(marker(document, "commentRangeStart", cid), starts[0].nextSibling)
    ends[0].parentNode.insertBefore(marker(document, "commentRangeEnd", cid), ends[0].nextSibling)
    parent_run = refs[0].parentNode
    parent_run.parentNode.insertBefore(reference_run(document, cid), parent_run.nextSibling)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Add a comment or reply to a .docx.")
    parser.add_argument("source", help="unpacked folder or .docx")
    parser.add_argument("text", help="comment text; use \\n for a new paragraph")
    parser.add_argument("--author", default="Eirene", help="author name (default: Eirene)")
    parser.add_argument("--anchor", help="attach the comment to the first occurrence of this text")
    parser.add_argument("--parent", help="reply to the comment with this id")
    parser.add_argument("-o", "--output", help="output .docx (packed input only; default: in place)")
    args = parser.parse_args()
    with opened(args.source, args.output) as folder:
        cid, _ = add_comment(folder, args.text.replace("\\n", "\n"), args.author, args.parent)
        document_path = folder / "word" / "document.xml"
        document = load(document_path)
        placed = (anchor_reply(document, cid, args.parent) if args.parent
                  else anchor_text(document, cid, args.anchor) if args.anchor else False)
        if placed:
            save(document, document_path)
    print(f"comment {cid} added" + (" and anchored" if placed else ""))
    if not placed:
        if args.anchor:
            print(f"could not find {args.anchor!r} inside a single run; run merge_runs.py, or place the markers yourself:",
                  file=sys.stderr)
        print(f'  <w:commentRangeStart w:id="{cid}"/>  …the commented runs…  <w:commentRangeEnd w:id="{cid}"/>\n'
              f'  <w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:commentReference w:id="{cid}"/></w:r>')
    return 0


if __name__ == "__main__":
    sys.exit(main())
