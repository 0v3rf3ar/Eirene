"""Edit Office XML without disturbing it.

ElementTree rewrites namespace prefixes and drops declarations it thinks are
unused, which breaks attributes such as mc:Ignorable="w14 w15". minidom keeps
prefixes and declarations exactly, so every script here edits through it.
"""

from __future__ import annotations

import xml.dom.minidom as minidom
from pathlib import Path

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
XML_NS = "http://www.w3.org/XML/1998/namespace"


def parse_bytes(data: bytes) -> minidom.Document:
    head = data[:4096]
    if b"<!DOCTYPE" in head or b"<!ENTITY" in head:
        raise ValueError("refusing XML with a DOCTYPE or entity declaration")
    return minidom.parseString(data)


def load(path: str | Path) -> minidom.Document:
    return parse_bytes(Path(path).read_bytes())


def save(document: minidom.Document, path: str | Path) -> None:
    data = document.toxml(encoding="UTF-8")
    if data.startswith(b'<?xml version="1.0" encoding="UTF-8"?>'):
        data = b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + data[38:]
    Path(path).write_bytes(data)


def children(node, namespace: str | None = None, name: str | None = None) -> list:
    """Element children, optionally filtered by namespace URI and local name."""
    return [c for c in node.childNodes if c.nodeType == c.ELEMENT_NODE
            and (namespace is None or c.namespaceURI == namespace)
            and (name is None or c.localName == name)]


def first(node, namespace: str, name: str):
    found = children(node, namespace, name)
    return found[0] if found else None


def elements(node, namespace: str, name: str) -> list:
    return list(node.getElementsByTagNameNS(namespace, name))


def prefix_for(document: minidom.Document, namespace: str, default: str) -> str:
    """The prefix the document already uses for a namespace, or default."""
    root = document.documentElement
    for index in range(root.attributes.length):
        attribute = root.attributes.item(index)
        if attribute.name.startswith("xmlns:") and attribute.value == namespace:
            return attribute.name[6:]
    root.setAttribute(f"xmlns:{default}", namespace)
    return default


def unwrap(node) -> None:
    """Replace node with its children."""
    parent = node.parentNode
    while node.firstChild is not None:
        parent.insertBefore(node.firstChild, node)
    parent.removeChild(node)


def remove(node) -> None:
    if node.parentNode is not None:
        node.parentNode.removeChild(node)


def text_of(node) -> str:
    if node.nodeType == node.TEXT_NODE:
        return node.data
    return "".join(text_of(c) for c in node.childNodes)


def set_text(document: minidom.Document, element, value: str) -> None:
    while element.firstChild is not None:
        element.removeChild(element.firstChild)
    element.appendChild(document.createTextNode(value))
    if value != value.strip() or "  " in value:
        element.setAttributeNS(XML_NS, "xml:space", "preserve")
    elif element.hasAttribute("xml:space"):
        element.removeAttribute("xml:space")
