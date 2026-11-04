#!/usr/bin/env python3
"""Measure how often a skill's description makes Eirene load it.

  python -m scripts.trigger_eval --eval-set trigger_evals.json --skill-path path/to/skill \\
      [--description "candidate text"] [--runs 3] [--parallel 4] [--model MODEL] [-o results.json]

The eval set is a list of {"query": ..., "should_trigger": true|false}. Each query
runs --runs times as `eirene -p QUERY` in a private Eirene home that has the
person's configuration and other skills plus this skill (with --description
swapped in, when given). A run counts as triggered when the model calls
load_skill for this skill. A query passes when its trigger rate is at least
--threshold (default 0.5) and it should trigger, or below it and it should not.
Prints JSON: per-query rates and a summary.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from utils import private_home, read_skill, run_stream, with_description
else:
    from .utils import private_home, read_skill, run_stream, with_description

import os


def prepare(skill: Path, description: str | None) -> tuple[Path, str]:
    meta, _, skill_md = read_skill(skill)
    name = meta.get("name") or skill.name
    staging = Path(tempfile.mkdtemp(prefix="trigger-skill-")) / name
    shutil.copytree(skill, staging, ignore=shutil.ignore_patterns("*-workspace", "__pycache__", ".git", "evals"))
    if description:
        (staging / "SKILL.md").write_text(with_description(skill_md.read_text(encoding="utf-8"), description),
                                          encoding="utf-8")
    home = private_home(staging, name)
    shutil.rmtree(staging.parent, ignore_errors=True)
    return home, name


def triggered_once(args, home: Path, name: str, query: str) -> bool:
    marker = f"{os.sep}skills{os.sep}{name}"
    hit = {"value": False}

    def watch(event: dict) -> bool:
        if event.get("type") == "tool_end" and event.get("name") == "load_skill":
            result = event.get("result") or ""
            if marker in result or f"/skills/{name}" in result:
                hit["value"] = True
                return True  # no need to let the run finish
        return False

    workdir = tempfile.mkdtemp(prefix="trigger-run-")
    try:
        command = [args.eirene, "-C", workdir, "-p", query, "--stream-json", "--tools", "read",
                   "--max-steps", str(args.max_steps), "--timeout", str(args.timeout)]
        if args.provider:
            command += ["--provider", args.provider]
        if args.model:
            command += ["--model", args.model]
        env = dict(os.environ, EIRENE_HOME=str(home))
        run_stream(command, timeout=args.timeout + 30, env=env, on_event=watch)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return hit["value"]


def evaluate(args, items: list[dict], description: str | None = None) -> dict:
    home, name = prepare(args.skill_path.resolve(), description)
    try:
        jobs = [(index, run) for index in range(len(items)) for run in range(args.runs)]
        with ThreadPoolExecutor(max_workers=max(1, args.parallel)) as pool:
            hits = list(pool.map(lambda job: triggered_once(args, home, name, items[job[0]]["query"]), jobs))
    finally:
        shutil.rmtree(home, ignore_errors=True)
    results = []
    for index, item in enumerate(items):
        count = sum(hit for (i, _), hit in zip(jobs, hits) if i == index)
        rate = count / args.runs
        passed = (rate >= args.threshold) == bool(item["should_trigger"])
        results.append({"query": item["query"], "should_trigger": bool(item["should_trigger"]),
                        "trigger_rate": round(rate, 3), "triggers": count, "runs": args.runs, "pass": passed})
    passed = sum(r["pass"] for r in results)
    return {"skill_name": name, "description": description, "results": results,
            "summary": {"passed": passed, "failed": len(results) - passed, "total": len(results),
                        "accuracy": round(passed / len(results), 3) if results else 0.0}}


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--skill-path", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=3, help="runs per query (default 3)")
    parser.add_argument("--parallel", type=int, default=4)
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--max-steps", type=int, default=4, help="tool rounds per run before giving up (default 4)")
    parser.add_argument("--timeout", type=int, default=180, help="seconds per run (default 180)")
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--eirene", default="eirene")


def main() -> int:
    parser = argparse.ArgumentParser(description="Trigger-rate evaluation for a skill description.")
    parser.add_argument("--eval-set", type=Path, required=True)
    parser.add_argument("--description", help="test this description instead of the one in SKILL.md")
    parser.add_argument("-o", "--output", type=Path)
    add_arguments(parser)
    args = parser.parse_args()
    items = json.loads(args.eval_set.read_text(encoding="utf-8"))
    report = evaluate(args, items, args.description)
    text = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
