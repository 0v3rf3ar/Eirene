#!/usr/bin/env python3
"""Open a browser page to review a test iteration: outputs, grades, benchmark, feedback.

  python eval-viewer/generate_review.py WORKSPACE/iteration-N --skill-name NAME \\
      [--benchmark WORKSPACE/iteration-N/benchmark.json] [--previous-workspace WORKSPACE/iteration-(N-1)] \\
      [--port 3117] [--static review.html] [--no-open]

Serves the page on http://127.0.0.1:PORT (local only). Each test case shows the
prompt, the with-skill output files rendered inline where possible, the baseline
output, the previous iteration's output, the grades, and a feedback box that
saves as you type. "Submit all reviews" writes ITERATION/feedback.json. Stop the
server with Ctrl+C (or kill its process) when the review is done.

--static writes one self-contained HTML file instead of serving; its Submit
button downloads feedback.json, which you then copy into the iteration folder.
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import sys
import threading
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TEXT_LIMIT = 200_000
BINARY_LIMIT = 15_000_000
TEXT_TYPES = {".md", ".txt", ".csv", ".tsv", ".json", ".py", ".js", ".mjs", ".ts", ".tsx", ".css", ".html",
              ".htm", ".xml", ".yaml", ".yml", ".toml", ".sh", ".sql", ".log", ".svg", ".ini", ".rst"}
ORDER = ["with_skill", "without_skill", "old_skill"]


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def file_entry(path: Path, root: Path) -> dict:
    relative = path.relative_to(root).as_posix()
    size = path.stat().st_size
    suffix = path.suffix.lower()
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    entry = {"name": relative, "size": size, "mime": mime}
    if suffix in TEXT_TYPES and size <= TEXT_LIMIT:
        try:
            entry["kind"] = "html" if suffix in (".html", ".htm") else "text"
            entry["text"] = path.read_text(encoding="utf-8")
            if suffix == ".svg":
                entry["kind"] = "image"
                entry["data"] = "data:image/svg+xml;base64," + base64.b64encode(path.read_bytes()).decode()
            return entry
        except UnicodeDecodeError:
            pass
    if size <= BINARY_LIMIT:
        entry["data"] = f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()
        entry["kind"] = "image" if mime.startswith("image/") else "pdf" if mime == "application/pdf" else "binary"
    else:
        entry["kind"] = "large"
        entry["path"] = str(path)
    return entry


def run_view(run_dir: Path) -> dict:
    outputs = run_dir / "outputs"
    files = [file_entry(p, outputs) for p in sorted(outputs.rglob("*")) if p.is_file()] if outputs.exists() else []
    grading = load_json(run_dir / "grading.json")
    transcript = run_dir / "transcript.md"
    return {"files": files, "grading": grading, "timing": load_json(run_dir / "timing.json"),
            "transcript": transcript.read_text(encoding="utf-8")[-60_000:] if transcript.exists() else ""}


def collect(iteration: Path, previous: Path | None) -> list[dict]:
    old_feedback = {}
    if previous:
        for review in load_json(previous / "feedback.json").get("reviews", []):
            old_feedback[review.get("run_id")] = review.get("feedback", "")
    cases = []
    for eval_dir in sorted(p for p in iteration.iterdir() if p.is_dir()):
        meta = load_json(eval_dir / "eval_metadata.json")
        if not meta and not (eval_dir / "with_skill").exists():
            continue
        name = meta.get("eval_name", eval_dir.name)
        configs = {}
        for config_dir in sorted((p for p in eval_dir.iterdir() if p.is_dir()),
                                 key=lambda p: ORDER.index(p.name) if p.name in ORDER else 9):
            runs = sorted(config_dir.glob("run-*"), key=lambda p: int(p.name.split("-")[-1]))
            if not runs and (config_dir / "outputs").exists():
                runs = [config_dir]
            if runs:
                configs[config_dir.name] = {"runs": len(runs), **run_view(runs[0])}
        case = {"run_id": f"{name}-with_skill", "eval_name": name, "prompt": meta.get("prompt", ""),
                "expected_output": meta.get("expected_output", ""), "configs": configs,
                "previous_feedback": old_feedback.get(f"{name}-with_skill", "")}
        if previous and (previous / eval_dir.name).exists():
            prev_dir = previous / eval_dir.name / "with_skill"
            prev_runs = sorted(prev_dir.glob("run-*")) or ([prev_dir] if (prev_dir / "outputs").exists() else [])
            if prev_runs:
                case["previous"] = run_view(prev_runs[0])
        cases.append(case)
    return cases


def build_page(args, iteration: Path, mode: str) -> str:
    template = (Path(__file__).resolve().parent / "viewer.html").read_text(encoding="utf-8")
    benchmark = load_json(Path(args.benchmark)) if args.benchmark else load_json(iteration / "benchmark.json")
    data = {"skill_name": args.skill_name, "iteration": iteration.name, "mode": mode,
            "cases": collect(iteration, Path(args.previous_workspace).resolve() if args.previous_workspace else None),
            "benchmark": benchmark, "feedback": load_json(iteration / "feedback.json")}
    payload = json.dumps(data).replace("</", "<\\/")
    return template.replace("/*__REVIEW_DATA__*/null", payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Review a skill test iteration in the browser.")
    parser.add_argument("iteration", type=Path)
    parser.add_argument("--skill-name", required=True)
    parser.add_argument("--benchmark")
    parser.add_argument("--previous-workspace", help="the previous iteration folder")
    parser.add_argument("--port", type=int, default=3117)
    parser.add_argument("--static", type=Path, help="write a standalone HTML file instead of serving")
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    iteration = args.iteration.resolve()
    if not iteration.is_dir():
        raise SystemExit(f"{iteration} is not a folder")
    if args.static:
        args.static.write_text(build_page(args, iteration, "static"), encoding="utf-8")
        print(f"wrote {args.static.resolve()}")
        if not args.no_open:
            webbrowser.open(args.static.resolve().as_uri())
        return 0

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            if self.path not in ("/", "/index.html"):
                self.send_error(404)
                return
            body = build_page(args, iteration, "server").encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path != "/feedback" or self.headers.get("Origin", f"http://127.0.0.1:{args.port}") not in (
                    f"http://127.0.0.1:{args.port}", f"http://localhost:{args.port}"):
                self.send_error(403)
                return
            length = min(int(self.headers.get("Content-Length", 0)), 5_000_000)
            try:
                data = json.loads(self.rfile.read(length))
                data.setdefault("saved_at", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
                (iteration / "feedback.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            except (ValueError, OSError) as exc:
                self.send_error(400, str(exc))
                return
            self.send_response(204)
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"review page: {url}  (feedback is saved to {iteration / 'feedback.json'}; Ctrl+C to stop)", flush=True)
    if not args.no_open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
