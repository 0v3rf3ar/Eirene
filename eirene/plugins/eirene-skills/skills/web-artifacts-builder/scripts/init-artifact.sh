#!/usr/bin/env bash
# Create a React + TypeScript + Tailwind + shadcn/ui project for a single-file artifact.
# Usage: init-artifact.sh [--minimal] PROJECT_NAME
set -euo pipefail

minimal=0
if [ "${1:-}" = "--minimal" ]; then minimal=1; shift; fi
if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ] || [ -z "${1:-}" ]; then
  echo "usage: $0 [--minimal] PROJECT_NAME"
  echo "  --minimal   skip adding the shadcn/ui component set"
  exit "$([ -z "${1:-}" ] && echo 2 || echo 0)"
fi
name="$1"
case "$name" in
  */*|.*|*" "*) echo "project name must be a plain folder name" >&2; exit 2 ;;
esac
if [ -e "$name" ]; then echo "$name already exists" >&2; exit 1; fi

command -v node >/dev/null || { echo "Node.js 18+ is required" >&2; exit 1; }
node_major=$(node -p 'process.versions.node.split(".")[0]')
if [ "$node_major" -lt 18 ]; then
  echo "Node.js 18+ is required (found $(node -v))" >&2; exit 1
fi
# pnpm must be startable by other programs (the shadcn CLI spawns it). Releases after
# 10 install a native binary from an install script, which newer npm versions block,
# leaving a stub that only a shell can run; pnpm 10 is plain JavaScript.
pnpm_works() {
  command -v pnpm >/dev/null && node -e 'require("child_process").execFileSync("pnpm", ["-v"], {stdio: "ignore"})' 2>/dev/null
}
if ! pnpm_works; then
  echo "installing pnpm 10 with npm (a pnpm that other programs can start)"
  npm install -g pnpm@10
  hash -r
  pnpm_works || { echo "pnpm still cannot be started; install it from https://pnpm.io/installation" >&2; exit 1; }
fi

echo "creating $name (Node $node_major)"
pnpm create vite@latest "$name" --template react-ts
cd "$name"

# Remove template leftovers.
node -e '
const fs = require("fs");
let html = fs.readFileSync("index.html", "utf8");
html = html.replace(/\s*<link rel="icon"[^>]*>/, "")
           .replace(/<title>.*<\/title>/, `<title>${process.argv[1]}</title>`);
fs.writeFileSync("index.html", html);
' "$name"
rm -f public/vite.svg src/assets/react.svg src/App.css

pnpm install
if [ "$node_major" -lt 20 ]; then
  pnpm add -D vite@5.4.11 @vitejs/plugin-react@4.3.4
fi

pnpm add -D tailwindcss@3.4.17 postcss autoprefixer @types/node tailwindcss-animate
pnpm add class-variance-authority clsx tailwind-merge lucide-react

cat > postcss.config.js <<'CFG'
export default {
  plugins: { tailwindcss: {}, autoprefixer: {} },
}
CFG

# Plain literal values only: the shadcn CLI rewrites this file and turns any helper
# function calls into strings, which silently breaks every theme color.
cat > tailwind.config.js <<'CFG'
import animate from "tailwindcss-animate"

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: { DEFAULT: "hsl(var(--primary))", foreground: "hsl(var(--primary-foreground))" },
        secondary: { DEFAULT: "hsl(var(--secondary))", foreground: "hsl(var(--secondary-foreground))" },
        destructive: { DEFAULT: "hsl(var(--destructive))", foreground: "hsl(var(--destructive-foreground))" },
        muted: { DEFAULT: "hsl(var(--muted))", foreground: "hsl(var(--muted-foreground))" },
        accent: { DEFAULT: "hsl(var(--accent))", foreground: "hsl(var(--accent-foreground))" },
        popover: { DEFAULT: "hsl(var(--popover))", foreground: "hsl(var(--popover-foreground))" },
        card: { DEFAULT: "hsl(var(--card))", foreground: "hsl(var(--card-foreground))" },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      keyframes: {
        "accordion-down": { from: { height: "0" }, to: { height: "var(--radix-accordion-content-height)" } },
        "accordion-up": { from: { height: "var(--radix-accordion-content-height)" }, to: { height: "0" } },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
      },
    },
  },
  plugins: [animate],
}
CFG

cat > src/index.css <<'CFG'
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  :root {
    --background: 0 0% 100%;
    --foreground: 0 0% 3.9%;
    --card: 0 0% 100%;
    --card-foreground: 0 0% 3.9%;
    --popover: 0 0% 100%;
    --popover-foreground: 0 0% 3.9%;
    --primary: 0 0% 9%;
    --primary-foreground: 0 0% 98%;
    --secondary: 0 0% 96.1%;
    --secondary-foreground: 0 0% 9%;
    --muted: 0 0% 96.1%;
    --muted-foreground: 0 0% 45.1%;
    --accent: 0 0% 96.1%;
    --accent-foreground: 0 0% 9%;
    --destructive: 0 84.2% 60.2%;
    --destructive-foreground: 0 0% 98%;
    --border: 0 0% 89.8%;
    --input: 0 0% 89.8%;
    --ring: 0 0% 3.9%;
    --radius: 0.5rem;
  }
  .dark {
    --background: 0 0% 3.9%;
    --foreground: 0 0% 98%;
    --card: 0 0% 3.9%;
    --card-foreground: 0 0% 98%;
    --popover: 0 0% 3.9%;
    --popover-foreground: 0 0% 98%;
    --primary: 0 0% 98%;
    --primary-foreground: 0 0% 9%;
    --secondary: 0 0% 14.9%;
    --secondary-foreground: 0 0% 98%;
    --muted: 0 0% 14.9%;
    --muted-foreground: 0 0% 63.9%;
    --accent: 0 0% 14.9%;
    --accent-foreground: 0 0% 98%;
    --destructive: 0 62.8% 30.6%;
    --destructive-foreground: 0 0% 98%;
    --border: 0 0% 14.9%;
    --input: 0 0% 14.9%;
    --ring: 0 0% 83.1%;
  }
  * { @apply border-border; }
  body { @apply bg-background text-foreground; }
}
CFG

# The @/ alias in every tsconfig that has compilerOptions (Vite's files contain comments).
node -e '
const fs = require("fs");
for (const file of ["tsconfig.json", "tsconfig.app.json"]) {
  if (!fs.existsSync(file)) continue;
  const text = fs.readFileSync(file, "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "")
    .replace(/,(\s*[}\]])/g, "$1");
  const config = JSON.parse(text);
  config.compilerOptions = { ...(config.compilerOptions || {}), baseUrl: ".", paths: { "@/*": ["./src/*"] } };
  fs.writeFileSync(file, JSON.stringify(config, null, 2) + "\n");
}
'

cat > vite.config.ts <<'CFG'
import path from "path"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
})
CFG

cat > components.json <<'CFG'
{
  "$schema": "https://ui.shadcn.com/schema.json",
  "style": "default",
  "rsc": false,
  "tsx": true,
  "tailwind": {
    "config": "tailwind.config.js",
    "css": "src/index.css",
    "baseColor": "neutral",
    "cssVariables": true,
    "prefix": ""
  },
  "aliases": {
    "components": "@/components",
    "utils": "@/lib/utils",
    "ui": "@/components/ui",
    "lib": "@/lib",
    "hooks": "@/hooks"
  }
}
CFG

mkdir -p src/lib
cat > src/lib/utils.ts <<'CFG'
import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
CFG

cat > src/App.tsx <<'CFG'
export default function App() {
  return (
    <main className="min-h-screen p-8">
      <h1 className="text-2xl font-semibold">Ready</h1>
      <p className="mt-2 text-muted-foreground">Edit src/App.tsx to build the app.</p>
    </main>
  )
}
CFG

if [ "$minimal" -eq 0 ]; then
  echo "adding shadcn/ui components"
  # shadcn 2.3 is the last line that targets Tailwind 3.
  pnpm dlx shadcn@2.3.0 add --yes --overwrite \
    accordion alert aspect-ratio avatar badge breadcrumb button calendar card carousel \
    checkbox collapsible command context-menu dialog drawer dropdown-menu form hover-card \
    input label menubar navigation-menu popover progress radio-group resizable scroll-area \
    select separator sheet skeleton slider sonner switch table tabs textarea toast toggle \
    toggle-group tooltip
fi

echo
echo "done: $name"
echo "  cd $name && pnpm dev      # live preview"
echo "  bash $(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/bundle-artifact.sh   # single-file build"
