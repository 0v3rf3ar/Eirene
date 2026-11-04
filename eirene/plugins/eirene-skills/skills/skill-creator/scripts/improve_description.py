#!/usr/bin/env python3
"""Ask a model for a better skill description, given which queries failed.

  python -m scripts.improve_description --skill-path path/to/skill --results trigger_results.json \\
      [--history history.json] [--model MODEL]

Runs one `eirene -p` request with the skill's current description and body, the
failing queries (missed triggers and false triggers), and earlier attempts, and
prints the proposed description. Used by optimize_description.py; can also be
run by hand.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from utils import read_skill
else:
    from .utils import read_skill

PROMPT = """You are improving the description of an agent skill. An agent sees only each \
skill's name and description when deciding whether to load it, so the description alone \
decides whether the skill is used.

Skill name: {name}

Current description:
<current>
{description}
</current>

What the skill contains (for context; the agent does not see this when deciding):
<skill_body>
{body}
</skill_body>

Results of testing the current description on realistic requests:
{failures}

Earlier descriptions tried, with their scores (avoid repeating what did not work):
{history}

Write a new description that:
- says plainly what the skill does and the situations it is for, including ones where the \
request does not name it ("even if they don't mention X");
- would make the agent load the skill for every "should trigger" request above and not for \
the "should not trigger" ones — fix the causes, do not list the test queries;
- leans towards triggering, since agents tend to under-use skills, but names nearby tasks it \
is not for when false triggers are the problem;
- stays under 1024 characters, uses no angle brackets, and is one paragraph.

Reply with the new description inside <new_description></new_description> and nothing else."""


def describe_failures(results: list[dict]) -> str:
    missed = [r for r in results if r["should_trigger"] and not r["pass"]]
    false = [r for r in results if not r["should_trigger"] and not r["pass"]]
    ok = [r for r in results if r["pass"]]
    lines = []
    if missed:
        lines.append("Should have triggered but did not:")
        lines += [f"- ({r['trigger_rate']:.0%} of runs) {r['query']}" for r in missed]
    if false:
        lines.append("Should not have triggered but did:")
        lines += [f"- ({r['trigger_rate']:.0%} of runs) {r['query']}" for r in false]
    lines.append(f"{len(ok)} other requests behaved correctly.")
    return "\n".join(lines)


def propose(skill: Path, results: list[dict], history: list[dict], *, eirene: str = "eirene",
            provider: str | None = None, model: str | None = None, timeout: int = 300) -> str:
    meta, body, _ = read_skill(skill)
    shown = "\n".join(f"- train {h.get('train_accuracy', '?')}, test {h.get('test_accuracy', '?')}: {h['description']}"
                      for h in history) or "(none yet)"
    prompt = PROMPT.format(name=meta.get("name", skill.name), description=meta.get("description", ""),
                           body=body[:12000], failures=describe_failures(results), history=shown)
    with tempfile.TemporaryDirectory(prefix="improve-") as workdir:
        command = [eirene, "-C", workdir, "-p", "-", "--json", "--quiet", "--tools", "read", "--skills", "none",
                   "--max-steps", "2", "--timeout", str(timeout)]
        if provider:
            command += ["--provider", provider]
        if model:
            command += ["--model", model]
        done = subprocess.run(command, input=prompt, capture_output=True, text=True, timeout=timeout + 60)
    try:
        output = json.loads(done.stdout.strip().splitlines()[-1]).get("output", "")
    except (IndexError, json.JSONDecodeError):
        raise SystemExit(f"eirene failed: {(done.stderr or done.stdout).strip()[-500:]}")
    match = re.search(r"<new_description>(.*?)</new_description>", output, re.S)
    text = " ".join((match.group(1) if match else output).split())
    return text.replace("<", "").replace(">", "")[:1024]


def main() -> int:
    parser = argparse.ArgumentParser(description="Propose an improved skill description.")
    parser.add_argument("--skill-path", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True, help="trigger_eval.py JSON output")
    parser.add_argument("--history", type=Path, help="JSON list of earlier attempts")
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--eirene", default="eirene")
    args = parser.parse_args()
    results = json.loads(args.results.read_text(encoding="utf-8"))["results"]
    history = json.loads(args.history.read_text(encoding="utf-8")) if args.history else []
    print(propose(args.skill_path.resolve(), results, history, eirene=args.eirene,
                  provider=args.provider, model=args.model))
    return 0


if __name__ == "__main__":
    sys.exit(main())
