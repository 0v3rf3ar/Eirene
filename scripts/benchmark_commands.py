"""Offline command/search latency benchmark. No model or network calls.

Run with the source directory to measure, e.g.:
  python scripts/benchmark_commands.py --source . --samples 15
Compare the median/p95 values on the same machine and fixture size.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=".")
    parser.add_argument("--samples", type=int, default=15)
    parser.add_argument("--files", type=int, default=1000)
    args = parser.parse_args()
    sys.path.insert(0, str(Path(args.source).resolve()))
    from eirene.tools import files
    from eirene.tools.sandbox import Sandbox
    from eirene.core import project

    with tempfile.TemporaryDirectory(prefix="eirene-command-bench-") as temp:
        root = Path(temp) / "project"
        root.mkdir()
        os.environ["EIRENE_HOME"] = str(Path(temp) / "home")
        (root / "pyproject.toml").write_text('[project]\nname="benchmark"\n')
        for index in range(args.files):
            target = root / "src" / f"module_{index:05}.py"
            target.parent.mkdir(exist_ok=True)
            target.write_text(f'def function_{index}():\n    return "needle {index}"\n')
        box = Sandbox(root)
        operations = {
            "small_read": lambda: files.read_file(box, "src/module_00000.py"),
            "file_discovery": lambda: files.glob_files(box, "**/*.py"),
            "text_search": lambda: files.search_text(box, "needle", "src", limit=100),
            "rare_search": lambda: files.search_text(
                box, f"function_{args.files - 1}", "src", limit=100
            ),
            "warm_profile": lambda: project.discover(root),
        }
        report = {}
        for name, operation in operations.items():
            operation()
            times = []
            for _ in range(args.samples):
                started = time.perf_counter()
                operation()
                times.append((time.perf_counter() - started) * 1000)
            report[name] = {
                "median_ms": round(statistics.median(times), 3),
                "p95_ms": round(sorted(times)[max(0, int(len(times) * 0.95) - 1)], 3),
            }
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
