"""List the buttons, links and form fields on a page, and save a screenshot.

Usage: python element_discovery.py [URL] [OUTPUT_DIR]
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5173"
out = Path(sys.argv[2] if len(sys.argv) > 2 else ".")
out.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(url)
    page.wait_for_load_state("networkidle")

    buttons = page.locator("button, [role=button]").all()
    print(f"{len(buttons)} buttons")
    for index, button in enumerate(buttons):
        label = button.inner_text().strip() if button.is_visible() else "(hidden)"
        print(f"  [{index}] {label or button.get_attribute('aria-label') or '(no text)'}")

    links = page.locator("a[href]").all()
    print(f"\n{len(links)} links (first 10)")
    for link in links[:10]:
        print(f"  {link.inner_text().strip() or '(no text)'} -> {link.get_attribute('href')}")

    fields = page.locator("input, textarea, select").all()
    print(f"\n{len(fields)} form fields")
    for field in fields:
        name = field.get_attribute("name") or field.get_attribute("id") or "(unnamed)"
        kind = field.get_attribute("type") or field.evaluate("e => e.tagName.toLowerCase()")
        print(f"  {name} ({kind})")

    shot = out / "page_discovery.png"
    page.screenshot(path=str(shot), full_page=True)
    print(f"\nscreenshot: {shot.resolve()}")
    browser.close()
