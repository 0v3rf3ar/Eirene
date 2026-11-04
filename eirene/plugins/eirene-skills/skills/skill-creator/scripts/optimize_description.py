#!/usr/bin/env python3
"""Improve a skill's description automatically against a trigger eval set.

  python -m scripts.optimize_description --eval-set trigger_evals.json --skill-path path/to/skill \\
      [--model MODEL] [--max-iterations 5] [--runs 3] [--out DIR] [--verbose]

Splits the eval set 60/40 into train and held-out test (keeping the share of
should/should-not queries), scores the current description on both, then
repeats: propose a new description from the train failures, score it. Stops when
every train query passes or after --max-iterations. The best description is
chosen by **test** score (then train score, then length), so it is not simply
fitted to the train queries. Writes history.json and report.html to --out and
prints JSON with best_description. SKILL.md is not changed.
"""

from __future__ import annotations

import argparse
import html
import json
import random
import sys
import time
import webbrowser
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from improve_description import propose
    from trigger_eval import add_arguments, evaluate
    from utils import read_skill
else:
    from .improve_description import propose
    from .trigger_eval import add_arguments, evaluate
    from .utils import read_skill


def split(items: list[dict], seed: int) -> tuple[list[dict], list[dict]]:
    rng = random.Random(seed)
    train, test = [], []
    for wanted in (True, False):
        group = [i for i in items if bool(i["should_trigger"]) == wanted]
        rng.shuffle(group)
        cut = max(1, round(len(group) * 0.6)) if len(group) > 1 else len(group)
        train += group[:cut]
        test += group[cut:]
    return train, test


def report_html(skill: str, history: list[dict], best: dict) -> str:
    rows = []
    for entry in history:
        mark = " best" if entry is best else ""
        rows.append(f"<tr class='{mark.strip()}'><td>{entry['iteration']}</td><td>{entry['train_accuracy']:.0%}</td>"
                    f"<td>{entry['test_accuracy']:.0%}</td><td>{html.escape(entry['description'])}</td></tr>")
    detail = []
    for entry in history:
        cells = "".join(
            f"<tr><td>{'test' if r.get('_test') else 'train'}</td><td>{'✓' if r['should_trigger'] else '✗'}</td>"
            f"<td>{r['trigger_rate']:.0%}</td><td class='{'ok' if r['pass'] else 'bad'}'>{'pass' if r['pass'] else 'fail'}</td>"
            f"<td>{html.escape(r['query'])}</td></tr>" for r in entry["results"])
        detail.append(f"<details><summary>Iteration {entry['iteration']}</summary><table><tr><th>Set</th>"
                      f"<th>Should</th><th>Rate</th><th>Result</th><th>Query</th></tr>{cells}</table></details>")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Description optimisation</title>
<style>
:root{{--bg:#fff;--fg:#1d1f23;--muted:#666;--line:#e3e3e3;--good:#1a7f37;--bad:#c62828;--hi:#eef5ff}}
@media (prefers-color-scheme:dark){{:root{{--bg:#16181c;--fg:#e6e6e6;--muted:#9a9a9a;--line:#30333a;--good:#5fd07d;--bad:#ff7b72;--hi:#1d2a3d}}}}
body{{margin:0;padding:24px 16px;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,sans-serif}}
main{{max-width:1000px;margin:auto}} table{{border-collapse:collapse;width:100%;margin:12px 0}}
td,th{{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}}
tr.best{{background:var(--hi)}} .ok{{color:var(--good)}} .bad{{color:var(--bad)}} .muted{{color:var(--muted)}}
blockquote{{margin:12px 0;padding:12px 16px;border-left:3px solid var(--good);background:var(--hi)}}
</style></head><body><main>
<h1>Description optimisation: {html.escape(skill)}</h1>
<p class="muted">Best is chosen by held-out test accuracy, then train accuracy, then length.</p>
<h2>Best (iteration {best['iteration']}: train {best['train_accuracy']:.0%}, test {best['test_accuracy']:.0%})</h2>
<blockquote>{html.escape(best['description'])}</blockquote>
<h2>Iterations</h2><table><tr><th>#</th><th>Train</th><th>Test</th><th>Description</th></tr>{''.join(rows)}</table>
<h2>Per query</h2>{''.join(detail)}
</main></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Optimise a skill description for triggering.")
    parser.add_argument("--eval-set", type=Path, required=True)
    parser.add_argument("--max-iterations", type=int, default=5)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, help="folder for history.json and report.html")
    parser.add_argument("--no-open", action="store_true", help="do not open the report in a browser")
    parser.add_argument("--verbose", action="store_true")
    add_arguments(parser)
    args = parser.parse_args()
    skill = args.skill_path.resolve()
    meta, _, _ = read_skill(skill)
    items = json.loads(args.eval_set.read_text(encoding="utf-8"))
    train, test = split(items, args.seed)
    out = (args.out or skill.parent / f"{skill.name}-workspace" / f"description-{time.strftime('%Y%m%d-%H%M%S')}").resolve()
    out.mkdir(parents=True, exist_ok=True)
    log = (lambda *a: print(*a, file=sys.stderr, flush=True)) if args.verbose else (lambda *a: None)
    log(f"{len(train)} train and {len(test)} test queries; results in {out}")

    history: list[dict] = []
    description = meta.get("description", "")
    for iteration in range(args.max_iterations + 1):
        scored = evaluate(args, train + test, description)
        results = scored["results"]
        for r in results[len(train):]:
            r["_test"] = True
        train_results, test_results = results[:len(train)], results[len(train):]
        entry = {
            "iteration": iteration, "description": description, "results": results,
            "train_accuracy": sum(r["pass"] for r in train_results) / max(1, len(train_results)),
            "test_accuracy": sum(r["pass"] for r in test_results) / max(1, len(test_results)),
        }
        history.append(entry)
        (out / "history.json").write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")
        log(f"iteration {iteration}: train {entry['train_accuracy']:.0%}, test {entry['test_accuracy']:.0%}")
        if entry["train_accuracy"] == 1.0 or iteration == args.max_iterations:
            break
        description = propose(skill, train_results, [{k: h[k] for k in ("description", "train_accuracy", "test_accuracy")}
                                                      for h in history],
                              eirene=args.eirene, provider=args.provider, model=args.model)
        log(f"  proposed: {description[:160]}{'…' if len(description) > 160 else ''}")

    best = max(history, key=lambda h: (h["test_accuracy"], h["train_accuracy"], -len(h["description"])))
    report = out / "report.html"
    report.write_text(report_html(meta.get("name", skill.name), history, best), encoding="utf-8")
    if not args.no_open:
        try:
            webbrowser.open(report.as_uri())
        except Exception:
            pass
    print(json.dumps({"best_description": best["description"], "best_iteration": best["iteration"],
                      "train_accuracy": best["train_accuracy"], "test_accuracy": best["test_accuracy"],
                      "original_description": meta.get("description", ""), "report": str(report),
                      "history": str(out / "history.json")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
