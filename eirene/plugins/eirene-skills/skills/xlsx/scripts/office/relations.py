"""Relationships and content types for unpacked Office folders."""

from __future__ import annotations

import posixpath
from pathlib import Path

from xmlutil import CT, REL, children, load, save

import xml.dom.minidom as minidom


def rels_file(folder: Path, part: str) -> Path:
    directory, name = posixpath.split(part)
    return folder / directory / "_rels" / f"{name}.rels"


def read(folder: Path, part: str) -> list[dict]:
    path = rels_file(folder, part)
    if not path.exists():
        return []
    return [{"id": r.getAttribute("Id"), "type": r.getAttribute("Type"), "target": r.getAttribute("Target"),
             "mode": r.getAttribute("TargetMode")}
            for r in children(load(path).documentElement, REL, "Relationship")]


def target_part(part: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(posixpath.dirname(part), target))


def relative(part: str, other: str) -> str:
    return posixpath.relpath(other, posixpath.dirname(part) or ".")


def add(folder: Path, part: str, rel_type: str, target_part_name: str) -> str:
    """Add a relationship from part to target_part_name; return its new Id (reuses an identical one)."""
    path = rels_file(folder, part)
    if path.exists():
        document = load(path)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        document = minidom.parseString(f'<Relationships xmlns="{REL}"/>'.encode())
    root = document.documentElement
    target = relative(part, target_part_name)
    existing = children(root, REL, "Relationship")
    for r in existing:
        if r.getAttribute("Type") == rel_type and target_part(part, r.getAttribute("Target")) == target_part_name:
            return r.getAttribute("Id")
    used = {r.getAttribute("Id") for r in existing}
    number = 1
    while f"rId{number}" in used:
        number += 1
    element = document.createElementNS(REL, "Relationship")
    element.setAttribute("Id", f"rId{number}")
    element.setAttribute("Type", rel_type)
    element.setAttribute("Target", target)
    root.appendChild(element)
    save(document, path)
    return f"rId{number}"


def remove_ids(folder: Path, part: str, ids: set[str]) -> None:
    path = rels_file(folder, part)
    if not path.exists() or not ids:
        return
    document = load(path)
    for r in children(document.documentElement, REL, "Relationship"):
        if r.getAttribute("Id") in ids:
            document.documentElement.removeChild(r)
    save(document, path)


def set_override(folder: Path, part: str, content_type: str | None) -> None:
    """Add (or with None, remove) the content-type override for /part."""
    path = folder / "[Content_Types].xml"
    document = load(path)
    root = document.documentElement
    name = "/" + part
    for override in children(root, CT, "Override"):
        if override.getAttribute("PartName") == name:
            if content_type is None:
                root.removeChild(override)
            else:
                override.setAttribute("ContentType", content_type)
            save(document, path)
            return
    if content_type is not None:
        element = document.createElementNS(CT, "Override")
        element.setAttribute("PartName", name)
        element.setAttribute("ContentType", content_type)
        root.appendChild(element)
        save(document, path)


def ensure_default(folder: Path, extension: str, content_type: str) -> None:
    path = folder / "[Content_Types].xml"
    document = load(path)
    root = document.documentElement
    if any(d.getAttribute("Extension").lower() == extension.lower() for d in children(root, CT, "Default")):
        return
    element = document.createElementNS(CT, "Default")
    element.setAttribute("Extension", extension)
    element.setAttribute("ContentType", content_type)
    root.insertBefore(element, root.firstChild)
    save(document, path)
