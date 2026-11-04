#!/usr/bin/env python3
"""Combine graded runs of one iteration into benchmark.json and benchmark.md.

  python -m scripts.aggregate_benchmark WORKSPACE/iteration-N --skill-name NAME [--skill-path PATH]

Reads every <eval>/<configuration>/run-K/grading.json (and timing.json,
metrics.json), then writes the per-run results, mean/stddev/min/max for pass
rate, time and tokens per configuration, and the difference between with_skill
and the baseline. Existing "notes" in benchmark.json are kept.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

ORDER = ["with_skill", "without_skill", "old_skill"]


def load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def stats(values: list[float]) -> dict:
    if not values:
        return {"mean": 0, "stddev": 0, "min": 0, "max": 0}
    return {"mean": round(statistics.fmean(values), 3),
            "stddev": round(statistics.pstdev(values), 3) if len(values) > 1 else 0.0,
            "min": round(min(values), 3), "max": round(max(values), 3)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate graded skill test runs.")
    parser.add_argument("iteration", type=Path)
    parser.add_argument("--skill-name", required=True)
    parser.add_argument("--skill-path", default="")
    args = parser.parse_args()
    iteration = args.iteration.resolve()
    runs, missing = [], []
    for eval_dir in sorted(p for p in iteration.iterdir() if p.is_dir()):
        meta = load(eval_dir / "eval_metadata.json")
        for config_dir in sorted((p for p in eval_dir.iterdir() if p.is_dir()),
                                 key=lambda p: ORDER.index(p.name) if p.name in ORDER else 9):
            for run_dir in sorted(config_dir.glob("run-*"), key=lambda p: int(p.name.split("-")[-1])):
                grading = load(run_dir / "grading.json")
                if not grading:
                    missing.append(run_dir.relative_to(iteration).as_posix())
                timing = load(run_dir / "timing.json")
                metrics = load(run_dir / "metrics.json")
                expectations = grading.get("expectations", [])
                passed = sum(1 for e in expectations if e.get("passed"))
                total = len(expectations)
                runs.append({
                    "eval_id": meta.get("eval_id"),
                    "eval_name": meta.get("eval_name", eval_dir.name),
                    "configuration": config_dir.name,
                    "run_number": int(run_dir.name.split("-")[-1]),
                    "result": {
                        "pass_rate": round(passed / total, 3) if total else 0.0,
                        "passed": passed, "failed": total - passed, "total": total,
                        "time_seconds": timing.get("total_duration_seconds", 0),
                        "tokens": timing.get("total_tokens", 0),
                        "tool_calls": metrics.get("total_tool_calls", 0),
                        "errors": metrics.get("errors_encountered", 0),
                    },
                    "expectations": expectations,
                    "notes": (grading.get("user_notes_summary") or {}).get("uncertainties", []),
                })
    configurations = [c for c in ORDER if any(r["configuration"] == c for r in runs)]
    summary = {}
    for config in configurations:
        chosen = [r["result"] for r in runs if r["configuration"] == config]
        summary[config] = {key: stats([float(r[key]) for r in chosen]) for key in ("pass_rate", "time_seconds", "tokens")}
    baseline = next((c for c in configurations if c != "with_skill"), None)
    if "with_skill" in summary and baseline:
        delta = {}
        for key, digits in (("pass_rate", 2), ("time_seconds", 1), ("tokens", 0)):
            diff = summary["with_skill"][key]["mean"] - summary[baseline][key]["mean"]
            delta[key] = f"{diff:+.{digits}f}"
        summary["delta"] = delta
    previous = load(iteration / "benchmark.json")
    benchmark = {
        "metadata": {
            "skill_name": args.skill_name, "skill_path": args.skill_path,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "evals_run": sorted({r["eval_name"] for r in runs}),
            "runs_per_configuration": max((r["run_number"] for r in runs), default=0),
        },
        "runs": runs, "run_summary": summary, "notes": previous.get("notes", []),
    }
    (iteration / "benchmark.json").write_text(json.dumps(benchmark, indent=2) + "\n", encoding="utf-8")

    lines = [f"# Benchmark: {args.skill_name}", "", f"{iteration}", "",
             "| Configuration | Pass rate | Time (s) | Tokens |", "| --- | --- | --- | --- |"]
    for config in configurations:
        s = summary[config]
        lines.append(f"| {config} | {s['pass_rate']['mean']:.0%} ± {s['pass_rate']['stddev']:.0%} | "
                     f"{s['time_seconds']['mean']:.1f} ± {s['time_seconds']['stddev']:.1f} | "
                     f"{s['tokens']['mean']:.0f} ± {s['tokens']['stddev']:.0f} |")
    if "delta" in summary:
        d = summary["delta"]
        lines.append(f"| delta | {d['pass_rate']} | {d['time_seconds']} | {d['tokens']} |")
    lines += ["", "## Per eval", "", "| Eval | Configuration | Run | Passed | Time (s) | Tokens |",
              "| --- | --- | --- | --- | --- | --- |"]
    for r in runs:
        res = r["result"]
        lines.append(f"| {r['eval_name']} | {r['configuration']} | {r['run_number']} | {res['passed']}/{res['total']} | "
                     f"{res['time_seconds']} | {res['tokens']} |")
    if benchmark["notes"]:
        lines += ["", "## Notes", ""] + [f"- {n}" for n in benchmark["notes"]]
    (iteration / "benchmark.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {iteration / 'benchmark.json'} and benchmark.md ({len(runs)} runs)")
    if missing:
        print(f"{len(missing)} run(s) have no grading.json yet: " + ", ".join(missing[:8]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
