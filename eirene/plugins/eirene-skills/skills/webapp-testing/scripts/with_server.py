#!/usr/bin/env python3
"""Start servers, wait until they listen, run a command, then stop the servers.

Examples:
  python with_server.py --server "npm run dev" --port 5173 -- python check.py
  python with_server.py --server "cd api && python app.py" --port 3000 \\
                        --server "cd web && npm run dev" --port 5173 -- pytest -q

Each --server needs a matching --port, in the same order. Servers start one at a
time; the next starts only once the previous one accepts TCP connections. The
exit status is the command's own. Server output goes to --log-dir if given,
otherwise it is discarded.
"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path


def listening(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def start(command: str, log: Path | None) -> subprocess.Popen:
    output = open(log, "wb") if log else subprocess.DEVNULL
    options: dict = {}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True  # so we can stop the whole tree
    return subprocess.Popen(command, shell=True, stdout=output, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, **options)


def stop(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)],
                           capture_output=True, check=False)
        else:
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        try:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a command while one or more servers are up.",
        epilog="Put the command to run after --.")
    parser.add_argument("--server", action="append", required=True, metavar="COMMAND",
                        help="shell command that starts a server (repeatable)")
    parser.add_argument("--port", action="append", type=int, required=True,
                        help="port the matching server listens on (repeatable)")
    parser.add_argument("--host", default="localhost", help="host to probe (default: localhost)")
    parser.add_argument("--timeout", type=float, default=30,
                        help="seconds to wait for each server (default: 30)")
    parser.add_argument("--log-dir", type=Path, help="write each server's output to server-N.log here")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="command to run once servers are ready")
    args = parser.parse_args()

    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("no command given; put it after --")
    if len(args.server) != len(args.port):
        parser.error("give exactly one --port for each --server")
    if args.log_dir:
        args.log_dir.mkdir(parents=True, exist_ok=True)

    running: list[subprocess.Popen] = []
    try:
        for index, (server, port) in enumerate(zip(args.server, args.port), 1):
            if listening(args.host, port):
                print(f"port {port} is already in use; stop whatever is listening there first",
                      file=sys.stderr)
                return 1
            print(f"[{index}/{len(args.server)}] starting: {server}", flush=True)
            log = args.log_dir / f"server-{index}.log" if args.log_dir else None
            process = start(server, log)
            running.append(process)
            deadline = time.monotonic() + args.timeout
            while not listening(args.host, port):
                if process.poll() is not None:
                    print(f"server exited with status {process.returncode} before listening on {port}",
                          file=sys.stderr)
                    return 1
                if time.monotonic() > deadline:
                    print(f"nothing listening on port {port} after {args.timeout:g}s", file=sys.stderr)
                    return 1
                time.sleep(0.3)
            print(f"ready on port {port}", flush=True)
        print("running: " + " ".join(command), flush=True)
        return subprocess.run(command).returncode
    except KeyboardInterrupt:
        return 130
    finally:
        for process in reversed(running):
            stop(process)
        if running:
            print(f"stopped {len(running)} server(s)", flush=True)


if __name__ == "__main__":
    sys.exit(main())
