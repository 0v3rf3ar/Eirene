#!/usr/bin/env python3
"""Validate the canonical version/tag and classify GitHub prereleases."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

CANONICAL = re.compile(r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:(a|b|rc)(?:0|[1-9][0-9]*))?\Z')


def is_prerelease(version: str) -> bool:
    match = CANONICAL.fullmatch(version)
    if not match:
        raise ValueError('Use a canonical version: X.Y.Z, X.Y.ZaN, X.Y.ZbN, or X.Y.ZrcN')
    return bool(match[1])


def classify(manifest: Path, tag: str = '') -> bool:
    content = manifest.read_text(encoding='utf-8')
    table = re.search(r'^\[project\][ \t]*\r?\n(.*?)(?=^\[|\Z)', content, re.M | re.S)
    fields = re.findall(r'^\s*version\s*=\s*["\']([^"\'\r\n]+)["\']', table[1] if table else '', re.M)
    if len(fields) != 1:
        raise ValueError('pyproject.toml must have one explicit project.version')
    version = fields[0]
    result = is_prerelease(version)
    if tag and tag != 'v' + version:
        raise ValueError(f'Release tag must match the manifest version: expected v{version}, got {tag}')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=Path(__file__).resolve().parents[1] / 'pyproject.toml')
    parser.add_argument('--tag', default='')
    args = parser.parse_args()
    try:
        print('true' if classify(args.manifest, args.tag) else 'false')
    except (ValueError, OSError) as exc:
        parser.exit(1, f'error: {exc}\n')


if __name__ == '__main__':
    main()
