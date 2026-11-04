#!/usr/bin/env bash
# Bundle the project in the current folder into one self-contained bundle.html.
set -euo pipefail

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  echo "usage: run from the project root: $0"
  echo "writes bundle.html with all scripts, styles and assets inlined"
  exit 0
fi
[ -f package.json ] || { echo "no package.json here; run this from the project root" >&2; exit 1; }
[ -f index.html ] || { echo "no index.html in the project root" >&2; exit 1; }
command -v pnpm >/dev/null || { echo "pnpm is required" >&2; exit 1; }

pnpm add -D parcel @parcel/config-default parcel-resolver-tspaths html-inline

if [ ! -f .parcelrc ]; then
  cat > .parcelrc <<'CFG'
{
  "extends": "@parcel/config-default",
  "resolvers": ["parcel-resolver-tspaths", "..."]
}
CFG
fi

rm -rf dist .parcel-cache bundle.html
pnpm exec parcel build index.html --dist-dir dist --no-source-maps --public-url ./
pnpm exec html-inline -b dist dist/index.html > bundle.html

size=$(wc -c < bundle.html | tr -d ' ')
echo
echo "bundle.html: $((size / 1024)) KB"
echo "open it directly in a browser; it needs no server"
