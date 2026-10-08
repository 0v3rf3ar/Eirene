"""Opt-in real-model coding evaluations: python -m eirene.evaluate --help."""
from __future__ import annotations

import argparse
import asyncio
import json
import shlex
import tempfile
import time
from pathlib import Path

from .core.agent import Agent, ToolFinished, TurnDone
from .core.config import Config
from .core.modes import Mode
from .core.session import Session
from .providers import registry
from .tools.sandbox import Sandbox
from .tools import shell

# Acceptance assertions stay in this runner, outside the writable task directory.
CASES = [
    {"id": "bug_fix", "files": {"calc.py": "def add(a, b):\n    return a - b\n"},
     "allowed": ["calc.py"],
     "prompt": "Fix add in calc.py so it correctly adds numbers. Verify the result.",
     "check": "from calc import add; assert add(2,3)==5; assert add(-2,2)==0"},
    {"id": "multi_file", "files": {"names.py": "def normalize(s):\n    return s\n",
      "greeting.py": "from names import normalize\ndef greet(s):\n    return 'Hello ' + normalize(s)\n"},
     "allowed": ["names.py", "greeting.py"],
     "prompt": "Make normalize trim whitespace and lowercase input. Change greet to return 'Hello, <normalized name>!'. Verify both modules.",
     "check": "from names import normalize; from greeting import greet; assert normalize(' ALICE ')== 'alice'; assert greet(' BOB ')== 'Hello, bob!'"},
    {"id": "preserve_user_work", "files": {"calc.py": "# User note: preserve this comment\ndef double(n):\n    return n\n",
     "notes.txt": "User's unfinished work: do not change.\n"},
     "allowed": ["calc.py"],
     "prompt": "Fix double in calc.py. Preserve the existing comment and leave notes.txt untouched. Verify the fix.",
     "check": "from calc import double; from pathlib import Path; assert double(7)==14; assert Path('calc.py').read_text().startswith('# User note: preserve this comment'); assert Path('notes.txt').read_text()==\"User's unfinished work: do not change.\\n\""},
    {"id": "failed_check", "files": {"calc.py": "def divide(a,b):\n    return a*b\n",
     "verify.py": "from calc import divide\nassert divide(9,3)==3\n"},
     "allowed": ["calc.py"],
     "prompt": "Run python3 verify.py, diagnose the failure, fix calc.py, and rerun verification. Do not edit verify.py.",
     "check": "from calc import divide; assert divide(9,3)==3; assert divide(5,2)==2.5"},
    {"id": "ambiguous_location", "files": {
        "server/auth.py": "def error_message():\n    return 'Login failed'\n",
        "client/auth.py": "def error_message():\n    return 'Login failed'\n",
        "client/screen.py": "from client.auth import error_message\ndef render():\n    return error_message()\n"},
     "allowed": ["client/auth.py"],
     "prompt": "The login screen's failure message should say 'Try signing in again'. Find the code that controls the displayed message and change it. Keep the server response unchanged. Verify it.",
     "check": "from client.screen import render; from server.auth import error_message; assert render()=='Try signing in again'; assert error_message()=='Login failed'"},
    {"id": "ignored_decoy", "files": {
        ".gitignore": "dist/\n",
        "src/formatting.py": "def title(s):\n    return s.lower()\n",
        "dist/formatting.py": "def title(s):\n    return s.lower()\n"},
     "allowed": ["src/formatting.py"],
     "prompt": "Our title formatter lowercases names. Locate its source and make it title-case them. Leave generated output untouched. Verify the change.",
     "check": "from src.formatting import title; assert title('ALICE smith')=='Alice Smith'"},

]


async def evaluate(args):
    config = Config.load()
    config.set("max_iterations", args.max_steps)
    config.set("auto_compact", True)
    key = registry.resolve_alias(args.provider)
    reports = []
    for case in CASES:
        if args.case and case["id"] != args.case:
            continue
        # Keep work and logs available for inspection; never delete results automatically.
        root = Path(tempfile.mkdtemp(prefix=f"eirene-eval-{case['id']}-"))
        for name, content in case["files"].items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(content)
        session = Session.create(root)
        agent = Agent(session, config, Sandbox(root))
        agent.mode = Mode.AUTO
        agent.use(registry.build(key, config), key, args.model)
        started = time.monotonic()
        status, calls, errors, interventions = "failed", 0, 0, 0
        async def approve(*_):
            nonlocal interventions
            interventions += 1
            return "no"
        agent.approve = approve
        try:
            async with asyncio.timeout(args.timeout):
                async for event in agent.run(case["prompt"]):
                    if isinstance(event, ToolFinished):
                        calls += 1
                        errors += int(event.is_error)
                    if isinstance(event, TurnDone):
                        status = event.status
        except TimeoutError:
            status = "timeout"
        finally:
            from .tools import processes
            await processes.stop_all()
            await agent.close()
            session.close()
        check = await shell.run("python3 -c " + shlex.quote(case["check"]), root,
            timeout=30, isolation=config.get("execution_isolation", "auto"),
            isolate_network=True)
        unexpected = [name for name, body in case["files"].items()
                      if name not in case["allowed"] and
                      (not (root / name).is_file() or (root / name).read_text() != body)]
        report = {"case": case["id"], "provider": key, "model": args.model,
                  "passed": check.ok and status == "completed" and not unexpected, "status": status,
                  "unexpected_changes": unexpected,
                  "seconds": round(time.monotonic() - started, 2), "tool_calls": calls,
                  "tool_errors": errors, "interventions": interventions,
                  "input_tokens": agent.usage.input_tokens, "output_tokens": agent.usage.output_tokens,
                  "estimated_cost": agent.usage.estimated_cost(config.get("model_costs", {})),
                  "workspace": str(root), "session": session.id, "verification": check.summary()}
        reports.append(report)
        print(json.dumps(report), flush=True)
    return 0 if reports and all(r["passed"] for r in reports) else 1


def main():
    parser = argparse.ArgumentParser(description="Run coding tasks against a real configured provider (uses tokens).")
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--case", choices=[c["id"] for c in CASES])
    parser.add_argument("--max-steps", type=int, default=30)
    parser.add_argument("--timeout", type=int, default=300)
    return asyncio.run(evaluate(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
