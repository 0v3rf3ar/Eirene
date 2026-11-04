#!/usr/bin/env python3
"""Evaluate an MCP server: run each question through Eirene and grade the answers.

  python evaluation.py questions.xml --server NAME [--server OTHER] [-o report.md]

The server must already be added to Eirene (/mcp add) and enabled in /mcp. Each
question runs as its own headless run:

  eirene -p PROMPT --mcp NAME --tools read --stream-json -C EMPTY_DIR

so the model has the granted MCP servers and nothing else useful: it runs in an
empty folder with read-only file tools. Answers are compared with the expected
value after trimming whitespace (case-sensitive unless --ignore-case).

Use --provider/--model to choose the model under test, --command to run some
other agent instead (it receives the prompt on stdin and must print the reply).
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PROMPT = """You are being evaluated on how well you can use the tools of an MCP server.

Answer the question below using only the MCP tools you have been given. Do not
guess: if the tools cannot give you the answer, say NOT_FOUND.

When you are done, reply with exactly these three tagged sections, in this order:

<summary>
The steps you took: which tools you called, in what order, with which inputs,
what came back, and how you reached the answer.
</summary>

<feedback>
Concrete feedback on the tools: are the names clear? Are the parameters well
described, and is it obvious which are required? Do the descriptions match what
the tools do? Did any call fail or return far too much? What specifically would
have made the task easier, and why?
</feedback>

<response>
Only the final answer — a number, ID, name or short text exactly as asked, or
NOT_FOUND — with nothing else.
</response>

Question: {question}"""


def load(path: Path) -> list[dict]:
    root = ET.parse(path).getroot()
    pairs = []
    for index, pair in enumerate(root.iter("qa_pair"), 1):
        question = (pair.findtext("question") or "").strip()
        answer = (pair.findtext("answer") or "").strip()
        if not question or not answer:
            raise SystemExit(f"qa_pair {index} needs both <question> and <answer>")
        pairs.append({"index": index, "question": question, "answer": answer})
    if not pairs:
        raise SystemExit(f"no <qa_pair> elements in {path}")
    return pairs


def tag(text: str, name: str) -> str:
    found = re.findall(rf"<{name}>(.*?)</{name}>", text, re.S)
    return found[-1].strip() if found else ""


def run_eirene(args, prompt: str, workdir: str) -> dict:
    command = [args.eirene, "-C", workdir, "-p", prompt, "--stream-json",
               "--tools", "read", "--timeout", str(args.timeout)]
    for server in args.server:
        command += ["--mcp", server]
    if args.provider:
        command += ["--provider", args.provider]
    if args.model:
        command += ["--model", args.model]
    if args.max_steps:
        command += ["--max-steps", str(args.max_steps)]
    started = time.monotonic()
    done = subprocess.run(command, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                          timeout=args.timeout + 60)
    seconds = time.monotonic() - started
    events = []
    for line in done.stdout.splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    final = next((e for e in reversed(events) if e.get("type") == "result"), None)
    if final is None:
        return {"text": "", "error": (done.stderr or done.stdout).strip()[-2000:] or f"exit {done.returncode}",
                "seconds": seconds, "tool_calls": 0, "tools": {}, "tokens": 0, "exit_code": done.returncode}
    result = final.get("result") or final
    # A server that failed to start or is not enabled shows up as an "MCP:" notice; the
    # run then goes on without its tools, so treat it as a setup failure, not a wrong answer.
    server_problems = [e.get("text", "") for e in events if e.get("type") == "notice"
                       and str(e.get("text", "")).startswith("MCP")]
    tools: dict[str, int] = {}
    for call in result.get("tool_calls") or []:
        tools[call.get("name", "?")] = tools.get(call.get("name", "?"), 0) + 1
    return {
        "text": result.get("output") or "",
        "error": "; ".join(result.get("errors") or []) if result.get("exit_code") else "",
        "seconds": result.get("duration_seconds") or seconds,
        "tool_calls": result.get("tool_call_count", len(result.get("tool_calls") or [])),
        "tools": tools,
        "tokens": (result.get("input_tokens") or 0) + (result.get("output_tokens") or 0),
        "status": result.get("status"),
        "exit_code": 3 if server_problems else result.get("exit_code", done.returncode),
        **({"error": "; ".join(server_problems)} if server_problems else {}),
    }


def run_command(args, prompt: str, workdir: str) -> dict:
    started = time.monotonic()
    done = subprocess.run(shlex.split(args.command), input=prompt, capture_output=True, text=True,
                          cwd=workdir, timeout=args.timeout + 60)
    return {"text": done.stdout, "error": "" if done.returncode == 0 else done.stderr.strip()[-2000:],
            "seconds": time.monotonic() - started, "tool_calls": 0, "tools": {}, "tokens": 0}


def evaluate(args, pair: dict) -> dict:
    prompt = PROMPT.format(question=pair["question"])
    with tempfile.TemporaryDirectory(prefix="mcp-eval-") as workdir:
        try:
            run = run_command(args, prompt, workdir) if args.command else run_eirene(args, prompt, workdir)
        except subprocess.TimeoutExpired:
            run = {"text": "", "error": "timed out", "seconds": args.timeout, "tool_calls": 0,
                   "tools": {}, "tokens": 0}
    response = tag(run["text"], "response")
    expected, got = pair["answer"].strip(), response.strip()
    correct = (got.casefold() == expected.casefold()) if args.ignore_case else got == expected
    status = "PASS" if correct else "FAIL"
    print(f"[{pair['index']}] {status}  expected {expected!r}, got {got!r}  "
          f"({run['tool_calls']} tool calls, {run['seconds']:.0f}s)", flush=True)
    return {**pair, **run, "response": got, "correct": correct,
            "summary": tag(run["text"], "summary"), "feedback": tag(run["text"], "feedback")}


def report(results: list[dict], args) -> str:
    total = len(results)
    passed = sum(r["correct"] for r in results)
    calls = sum(r["tool_calls"] for r in results)
    seconds = sum(r["seconds"] for r in results)
    tokens = sum(r["tokens"] for r in results)
    target = args.command or "eirene " + " ".join(f"--mcp {s}" for s in args.server)
    lines = [
        "# MCP evaluation report", "",
        f"- **Target:** `{target}`" + (f" · provider `{args.provider}`" if args.provider else "")
        + (f" · model `{args.model}`" if args.model else ""),
        f"- **Accuracy:** {passed}/{total} ({passed / total:.0%})",
        f"- **Average time per question:** {seconds / total:.1f}s",
        f"- **Average tool calls per question:** {calls / total:.1f} ({calls} in total)",
        f"- **Tokens:** {tokens:,} in total", "",
        "| # | Result | Expected | Got | Tool calls | Seconds |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        cell = lambda v: str(v).replace("|", "\\|").replace("\n", " ")[:80]
        lines.append(f"| {r['index']} | {'pass' if r['correct'] else 'fail'} | {cell(r['answer'])} | "
                     f"{cell(r['response'])} | {r['tool_calls']} | {r['seconds']:.0f} |")
    for r in results:
        lines += ["", f"## Question {r['index']} — {'pass' if r['correct'] else 'fail'}", "",
                  f"**Question:** {r['question']}", "",
                  f"**Expected:** `{r['answer']}` · **Got:** `{r['response']}`", ""]
        if r.get("error"):
            lines += [f"**Error:** {r['error']}", ""]
        if r["tools"]:
            lines += ["**Tools used:** " + ", ".join(f"`{n}` ×{c}" for n, c in sorted(r["tools"].items())), ""]
        if r["summary"]:
            lines += ["**Approach**", "", r["summary"], ""]
        if r["feedback"]:
            lines += ["**Feedback on the tools**", "", r["feedback"], ""]
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate an MCP server with Eirene headless runs.")
    parser.add_argument("questions", type=Path, help="XML file of <qa_pair> elements")
    parser.add_argument("--server", action="append", default=[],
                        help="MCP server name as shown in /mcp (repeatable)")
    parser.add_argument("--provider", help="provider to evaluate with (default: the active one)")
    parser.add_argument("--model", help="model to evaluate with")
    parser.add_argument("--eirene", default="eirene", help="path to the eirene executable")
    parser.add_argument("--command", help="run this agent command instead; it gets the prompt on stdin")
    parser.add_argument("--timeout", type=int, default=600, help="seconds per question (default 600)")
    parser.add_argument("--max-steps", type=int, help="stop each run after this many tool rounds")
    parser.add_argument("--parallel", type=int, default=1, help="questions to run at once (default 1)")
    parser.add_argument("--ignore-case", action="store_true", help="compare answers without case")
    parser.add_argument("-o", "--output", type=Path, help="write the Markdown report here")
    args = parser.parse_args()
    if not args.command and not args.server:
        parser.error("give at least one --server (or --command)")

    pairs = load(args.questions)
    print(f"{len(pairs)} questions from {args.questions}", flush=True)
    # Run the first question alone: a setup problem (bad flag, unknown server, no
    # provider, rejected key) fails every question the same way, so stop early.
    first = evaluate(args, pairs[0])
    if first.get("exit_code") in (2, 3, 4):
        print(f"stopping: the run could not start ({first.get('error') or 'see above'}).\n"
              "Check the server name in /mcp, that it is enabled and starts, and that a provider is connected.",
              file=sys.stderr)
        return 2
    with ThreadPoolExecutor(max_workers=max(1, args.parallel)) as pool:
        results = [first] + list(pool.map(lambda pair: evaluate(args, pair), pairs[1:]))
    text = report(results, args)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
        print(f"report: {args.output.resolve()}")
    else:
        print("\n" + text)
    passed = sum(r["correct"] for r in results)
    print(f"accuracy {passed}/{len(results)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
