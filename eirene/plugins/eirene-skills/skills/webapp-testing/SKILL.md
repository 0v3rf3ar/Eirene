---
name: webapp-testing
description: Test and inspect local web applications with Playwright for Python — check that a frontend works, debug UI behaviour, take screenshots and capture browser console output. Use for any task that needs a real browser on a local or file:// page.
---

# Web application testing

Test local web apps by writing short Python Playwright scripts.

**Requirements:** Python 3 with `playwright` (`pip install playwright`) and a
browser (`python -m playwright install chromium`). Ask before installing them.

**Helper script:**

- `scripts/with_server.py` — starts one or more dev servers, waits until they
  accept connections, runs your command, then shuts the servers down.

**Run helpers with `--help` first.** Treat them as black boxes: call them rather
than reading their source, unless running them shows you need something they do
not do. Reading them only fills your context.

## Pick an approach

```
What are you testing?
├─ A static HTML file
│   ├─ Read the file to find selectors
│   │   ├─ Found them → write the Playwright script with those selectors
│   │   └─ Not enough (content built by JS) → treat it as dynamic ↓
│
└─ A dynamic app
    ├─ Server not running → python scripts/with_server.py --help
    │                       then run your script through the helper
    └─ Server running → look first, then act:
        1. open the page and wait for networkidle
        2. take a screenshot or read the DOM
        3. find selectors in the rendered page
        4. act using those selectors
```

## Using with_server.py

One server:

```bash
python scripts/with_server.py --server "npm run dev" --port 5173 -- python check_app.py
```

Several (for example an API and a frontend):

```bash
python scripts/with_server.py \
  --server "cd backend && python server.py" --port 3000 \
  --server "cd frontend && npm run dev" --port 5173 \
  -- python check_app.py
```

Your script then contains only browser logic — the servers are already up:

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)  # always headless
    page = browser.new_page()
    page.goto("http://localhost:5173")
    page.wait_for_load_state("networkidle")  # let the JavaScript finish
    # ... checks and actions
    browser.close()
```

## Look, then act

1. **Inspect what rendered:**
   ```python
   page.screenshot(path="inspect.png", full_page=True)
   html = page.content()
   buttons = page.locator("button").all()
   ```
   Then look at the screenshot (if your model can read images) or the HTML.
2. **Choose selectors** from what you saw.
3. **Act** with those selectors and check the result.

## The usual mistake

- **Don't** read the DOM of a dynamic app before it settles.
- **Do** call `page.wait_for_load_state("networkidle")` first (or wait for a
  specific element with `page.wait_for_selector(...)`).

## Good practice

- Reach for the helper scripts before writing your own server management.
- Use `sync_playwright()` for simple scripts.
- Always close the browser.
- Prefer meaningful selectors: `text=`, `role=`, ids, stable CSS classes —
  `page.get_by_role("button", name="Save")` survives redesigns.
- Wait for conditions (`wait_for_selector`, `expect(...)`) rather than fixed
  sleeps; use `page.wait_for_timeout()` only as a last resort.
- Write screenshots and logs into the project or a temporary folder you name,
  and tell the person where they are.

## Examples

`examples/` has short, complete scripts:

- `element_discovery.py` — list the buttons, links and inputs on a page
- `static_html_automation.py` — drive a local HTML file through a `file://` URL
- `console_logging.py` — collect browser console messages while interacting
