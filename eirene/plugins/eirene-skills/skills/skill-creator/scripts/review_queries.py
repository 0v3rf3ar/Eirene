#!/usr/bin/env python3
"""Open the trigger-query review page for a skill, prefilled with an eval set.

  python -m scripts.review_queries --skill-path path/to/skill --eval-set trigger_evals.json [--out review.html]

Writes a standalone page (default: next to the eval set) where the person can
edit queries, flip should/should-not, add or delete entries, and export the
result as eval_set.json (it lands in their downloads folder). Edits are kept in
the browser between reloads.
"""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from utils import read_skill
else:
    from .utils import read_skill


def safe(value) -> str:
    return json.dumps(value).replace("</", "<\\/")


def main() -> int:
    parser = argparse.ArgumentParser(description="Review trigger test queries in the browser.")
    parser.add_argument("--skill-path", type=Path, required=True)
    parser.add_argument("--eval-set", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    meta, _, _ = read_skill(args.skill_path)
    items = json.loads(args.eval_set.read_text(encoding="utf-8"))
    template = (Path(__file__).resolve().parent.parent / "assets" / "eval_review.html").read_text(encoding="utf-8")
    page = (template.replace("__EVAL_DATA_PLACEHOLDER__", safe(items))
                    .replace("__SKILL_NAME_PLACEHOLDER__", safe(meta.get("name", args.skill_path.name)))
                    .replace("__SKILL_DESCRIPTION_PLACEHOLDER__", safe(meta.get("description", ""))))
    out = (args.out or args.eval_set.with_name(f"review_{meta.get('name', 'skill')}.html")).resolve()
    out.write_text(page, encoding="utf-8")
    print(f"wrote {out}\nwhen the person exports, look for the newest eval_set*.json in their downloads folder")
    if not args.no_open:
        webbrowser.open(out.as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
