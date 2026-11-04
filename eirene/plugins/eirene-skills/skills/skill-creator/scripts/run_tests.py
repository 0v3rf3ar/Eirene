#!/usr/bin/env python3
"""Run a skill's test prompts with and without the skill, as Eirene headless runs.

  python -m scripts.run_tests --skill path/to/skill --evals path/to/skill/evals/evals.json \\
      --workspace path/to/skill-workspace [--baseline none|PATH] [--runs 1] [--parallel 3]

For every eval in evals.json it runs the prompt twice per run number:

  with_skill      the agent is told to read and follow the skill (a copy is put
                  in the run folder at ./skill)
  without_skill   (--baseline none, the default) the same prompt with no skill
  old_skill       (--baseline PATH) the same prompt with an older copy of the skill

Results go to WORKSPACE/iteration-N/<eval-name>/<configuration>/run-K/:

  outputs/        the run's working folder contents; eval input files are copied in first
  transcript.md   prompt, tool calls, results and the final answer, for graders and you
  events.jsonl    the raw --stream-json events
  timing.json     {total_tokens, duration_ms, total_duration_seconds}
  metrics.json    tool-call counts, errors, output size

and eval_metadata.json beside the configuration folders. N defaults to the next
unused iteration. Each run starts with --skills none so other installed skills do
not interfere, and keeps Eirene's normal sandbox and Auto mode.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from utils import read_skill, result_of, run_stream
else:
    from .utils import read_skill, result_of, run_stream

SKILL_PROMPT = """A skill for this kind of task is in ./skill. Before you start, read ./skill/SKILL.md \
and follow it; its scripts and reference files are in ./skill as well.

"""
TASK_PROMPT = """{skill}Task:
{prompt}

Work in this folder. Save every file you produce in ./outputs (input files, if any, are there \
already). When you are done, reply with a short summary of what you produced and anything you \
were unsure about."""
IGNORE = shutil.ignore_patterns("*-workspace", "__pycache__", ".git", "node_modules", "evals")


def slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return value[:48] or "eval"


def next_iteration(workspace: Path) -> int:
    numbers = [int(m.group(1)) for p in workspace.glob("iteration-*") if (m := re.fullmatch(r"iteration-(\d+)", p.name))]
    return max(numbers, default=0) + 1


def transcript(prompt: str, events: list[dict]) -> str:
    lines = ["# Transcript", "", "## Prompt", "", prompt, "", "## Steps", ""]
    text: list[str] = []
    step = 0
    for event in events:
        kind = event.get("type")
        if kind == "text":
            text.append(event.get("text", ""))
        elif kind == "tool_start":
            if text and "".join(text).strip():
                lines += ["", "".join(text).strip(), ""]
            text = []
            step += 1
            lines.append(f"### Step {step}: {event.get('name')} — {event.get('label', '')}")
        elif kind == "tool_end":
            result = (event.get("result") or "").strip()
            status = "error" if event.get("is_error") else "ok"
            lines += [f"Result ({status}, {event.get('seconds', 0):.1f}s):", "", "```", result[:2000], "```", ""]
        elif kind == "notice":
            lines.append(f"> {event.get('text', '')}")
        elif kind == "error":
            lines.append(f"**Error ({event.get('kind', '')}):** {event.get('text', '')}")
    lines += ["## Final answer", "", "".join(text).strip() or "(none)", ""]
    return "\n".join(lines)


def run_one(args, eval_item: dict, configuration: str, run_number: int, run_dir: Path, skill_copy: Path | None) -> dict:
    if run_dir.exists():
        shutil.rmtree(run_dir)
    outputs = run_dir / "outputs"
    outputs.mkdir(parents=True)
    for name in eval_item.get("files", []):
        source = (args.evals.parent / name).resolve() if not Path(name).is_absolute() else Path(name)
        if source.is_dir():
            shutil.copytree(source, outputs / source.name)
        elif source.exists():
            shutil.copy2(source, outputs / source.name)
        else:
            print(f"warning: eval {eval_item.get('id')}: input {name} not found", file=sys.stderr)
    if skill_copy is not None:
        shutil.copytree(skill_copy, run_dir / "skill", ignore=IGNORE)
    prompt = TASK_PROMPT.format(skill=SKILL_PROMPT if skill_copy is not None else "", prompt=eval_item["prompt"])
    command = [args.eirene, "-C", str(run_dir), "-p", prompt, "--stream-json", "--skills", "none",
               "--timeout", str(args.timeout)]
    if args.provider:
        command += ["--provider", args.provider]
    if args.model:
        command += ["--model", args.model]
    events, code, stderr = run_stream(command, timeout=args.timeout + 60)
    with open(run_dir / "events.jsonl", "w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event) + "\n")
    (run_dir / "transcript.md").write_text(transcript(prompt, events), encoding="utf-8")
    result = result_of(events)
    tokens = (result.get("input_tokens") or 0) + (result.get("output_tokens") or 0)
    seconds = float(result.get("duration_seconds") or 0)
    (run_dir / "timing.json").write_text(json.dumps({
        "total_tokens": tokens, "duration_ms": int(seconds * 1000), "total_duration_seconds": round(seconds, 1),
    }, indent=2) + "\n", encoding="utf-8")
    calls: dict[str, int] = {}
    for call in result.get("tool_calls") or []:
        calls[call.get("name", "?")] = calls.get(call.get("name", "?"), 0) + 1
    output_chars = sum(p.stat().st_size for p in outputs.rglob("*") if p.is_file())
    (run_dir / "metrics.json").write_text(json.dumps({
        "tool_calls": calls, "total_tool_calls": result.get("tool_call_count", sum(calls.values())),
        "errors_encountered": sum(1 for c in result.get("tool_calls") or [] if c.get("is_error")),
        "output_chars": output_chars, "status": result.get("status"), "exit_code": result.get("exit_code", code),
    }, indent=2) + "\n", encoding="utf-8")
    status = result.get("status") or f"exit {code}"
    print(f"{eval_item['_name']} / {configuration} / run-{run_number}: {status}, {seconds:.0f}s, {tokens} tokens",
          flush=True)
    if not result and stderr:
        print(f"  {stderr.strip()[-400:]}", file=sys.stderr)
    return {"eval": eval_item["_name"], "configuration": configuration, "run": run_number, "status": status}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run skill test prompts with and without the skill.")
    parser.add_argument("--skill", type=Path, required=True)
    parser.add_argument("--evals", type=Path, help="evals.json (default: SKILL/evals/evals.json)")
    parser.add_argument("--workspace", type=Path, help="default: SKILL-workspace next to the skill")
    parser.add_argument("--iteration", type=int, help="default: the next unused number")
    parser.add_argument("--baseline", default="none", help="'none' for no skill, or a path to an older copy")
    parser.add_argument("--runs", type=int, default=1, help="runs per configuration (default 1)")
    parser.add_argument("--parallel", type=int, default=3)
    parser.add_argument("--only", type=int, nargs="*", help="eval ids to run")
    parser.add_argument("--timeout", type=int, default=900, help="seconds per run (default 900)")
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--eirene", default="eirene", help="eirene executable")
    args = parser.parse_args()

    skill = args.skill.resolve()
    meta, _, _ = read_skill(skill)
    args.evals = (args.evals or skill / "evals" / "evals.json").resolve()
    workspace = (args.workspace or skill.parent / f"{skill.name}-workspace").resolve()
    data = json.loads(args.evals.read_text(encoding="utf-8"))
    evals = [e for e in data.get("evals", []) if not args.only or e.get("id") in args.only]
    if not evals:
        raise SystemExit("no evals to run")
    iteration = workspace / f"iteration-{args.iteration or next_iteration(workspace)}"
    baseline = None if args.baseline == "none" else Path(args.baseline).resolve()
    base_name = "without_skill" if baseline is None else "old_skill"

    jobs = []
    for item in evals:
        item["_name"] = item.get("name") or f"eval-{item.get('id', len(jobs))}-{slug(item['prompt'][:40])}"
        folder = iteration / item["_name"]
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "eval_metadata.json").write_text(json.dumps({
            "eval_id": item.get("id"), "eval_name": item["_name"], "prompt": item["prompt"],
            "expected_output": item.get("expected_output", ""), "files": item.get("files", []),
            "assertions": item.get("assertions", []),
        }, indent=2) + "\n", encoding="utf-8")
        for run in range(1, args.runs + 1):
            jobs.append((item, "with_skill", run, folder / "with_skill" / f"run-{run}", skill))
            jobs.append((item, base_name, run, folder / base_name / f"run-{run}", baseline))
    print(f"{meta.get('name', skill.name)}: {len(jobs)} runs into {iteration}", flush=True)
    with ThreadPoolExecutor(max_workers=max(1, args.parallel)) as pool:
        results = list(pool.map(lambda job: run_one(args, *job), jobs))
    failed = [r for r in results if r["status"] not in ("completed",)]
    print(f"done: {len(results) - len(failed)} completed, {len(failed)} not completed")
    print(f"iteration folder: {iteration}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
