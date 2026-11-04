---
name: web-artifacts-builder
description: Build larger single-file HTML apps with React, TypeScript, Tailwind CSS and shadcn/ui, then bundle them into one self-contained HTML file. Use for interactive pages that need state, routing or many UI components — not for a simple page you can write by hand in one HTML file.
---

# Web artifacts builder

For a rich interactive page that should end up as **one HTML file** anyone can
open — no server, no build step on their side:

1. Create the project with `scripts/init-artifact.sh`.
2. Build the app by editing the generated source.
3. Bundle everything into a single file with `scripts/bundle-artifact.sh`.
4. Hand the file to the person (and publish it if your session has a way to).
5. Optionally, test it.

**Stack:** React 18 + TypeScript, Vite for development, Parcel for the
single-file bundle, Tailwind CSS 3 and shadcn/ui components.

**Requirements:** Node.js 18 or newer, network access to the npm registry, and
`pnpm` (the init script offers to install it with npm). Ask before installing.

## Design

Avoid the look people call "AI slop": everything centered, purple gradients, one
border radius on every element, and Inter as the only font. If the
`frontend-design` skill is available, load it and make a design plan before
writing components.

## Step 1 — create the project

```bash
bash scripts/init-artifact.sh my-app
cd my-app
```

You get:

- React + TypeScript from the Vite template
- Tailwind CSS 3.4 with the shadcn/ui CSS-variable theme (light and dark)
- the `@/` import alias for `src/`
- the common shadcn/ui components, added with the official shadcn CLI
- Radix UI and the other libraries those components need
- a Vite version that works on your Node.js (pinned to 5.x on Node 18)

Pass `--minimal` to skip the component set and add components later with
`pnpm dlx shadcn@latest add NAME`.

## Step 2 — build the app

Edit `src/App.tsx` and add components under `src/`. Import UI components with the
alias:

```tsx
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
```

Run `pnpm dev` for a live preview while you work.

Keep everything local: no runtime fetches to your own backend, because the
bundled file has none. Data the app needs goes into the source or is entered by
the person in the page.

## Step 3 — bundle to one file

From the project root:

```bash
bash /path/to/scripts/bundle-artifact.sh
```

This produces `bundle.html` with all JavaScript, CSS and assets inlined. The
project root must contain `index.html`.

The script:

- adds the bundling packages (`parcel`, `@parcel/config-default`,
  `parcel-resolver-tspaths`, `html-inline`) as dev dependencies;
- writes a `.parcelrc` that understands the `@/` alias;
- builds with Parcel without source maps;
- inlines every asset into `bundle.html` and prints its size.

## Step 4 — deliver

Give the person the path to `bundle.html`. It opens directly in a browser. If your
session has a tool for publishing pages, offer to publish it.

## Step 5 — test (optional)

Only when asked, or when something seems wrong. Testing before you hand the file
over delays the result; do it afterwards if needed. Use the `webapp-testing`
skill or another browser tool, and open the bundle with a `file://` URL.

## Reference

- shadcn/ui components: https://ui.shadcn.com/docs/components
