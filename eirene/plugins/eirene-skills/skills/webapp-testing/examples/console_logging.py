"""Collect browser console messages and page errors while using a page.

Usage: python console_logging.py [URL] [OUTPUT_FILE]
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5173"
log_file = Path(sys.argv[2] if len(sys.argv) > 2 else "console.log")
messages: list[str] = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.on("console", lambda msg: messages.append(f"[{msg.type}] {msg.text}"))
    page.on("pageerror", lambda error: messages.append(f"[pageerror] {error}"))

    page.goto(url)
    page.wait_for_load_state("networkidle")
    # Interact to trigger the behaviour you are debugging, for example:
    # page.click("text=Dashboard")
    # page.wait_for_load_state("networkidle")
    browser.close()

log_file.write_text("\n".join(messages) + "\n", encoding="utf-8")
for line in messages:
    print(line)
print(f"\n{len(messages)} messages saved to {log_file.resolve()}")
