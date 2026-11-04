"""Drive a local HTML file through a file:// URL: screenshot, fill a form, submit.

Usage: python static_html_automation.py PATH/TO/page.html [OUTPUT_DIR]
Adjust the selectors below to the page you are testing.
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

page_file = Path(sys.argv[1] if len(sys.argv) > 1 else "index.html").resolve()
out = Path(sys.argv[2] if len(sys.argv) > 2 else ".")
out.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.goto(page_file.as_uri())
    page.screenshot(path=str(out / "before.png"), full_page=True)

    page.click("text=Click Me")
    page.fill("#name", "Ada Lovelace")
    page.fill("#email", "ada@example.com")
    page.click("button[type=submit]")
    page.wait_for_load_state()

    page.screenshot(path=str(out / "after.png"), full_page=True)
    browser.close()

print(f"screenshots in {out.resolve()}")
