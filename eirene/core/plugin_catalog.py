"""Portable bundles offered by /plugins browse and install shortcuts."""

OFFICIAL = "anthropics/claude-plugins-official"

# name, source, purpose/prerequisites; keep suggestions usable by the importer.
BUNDLES = (
    ("ponytail", "DietrichGebert/ponytail", "minimal implementations; hooks need Node.js and trust"),
    ("superpowers", "obra/superpowers", "planning, debugging, testing; startup hook needs trust"),
    ("anthropic-skills", "anthropics/skills", "frontend design, documents, skill authoring"),
    ("frontend-design", f"{OFFICIAL}/plugins/frontend-design", "frontend design guidance"),
    ("code-review", f"{OFFICIAL}/plugins/code-review", "code review instructions; native delegation is not emulated"),
    ("commit-commands", f"{OFFICIAL}/plugins/commit-commands", "commit and pull request workflows; Git/GitHub CLI"),
    ("pr-review-toolkit", f"{OFFICIAL}/plugins/pr-review-toolkit", "review prompts and specialist instructions; native delegation is not emulated"),
    ("feature-dev", f"{OFFICIAL}/plugins/feature-dev", "feature planning and implementation; native delegation is not emulated"),
    ("playwright", f"{OFFICIAL}/external_plugins/playwright", "browser MCP tools; Node.js/npx, browser dependencies, and trust"),
    ("serena", f"{OFFICIAL}/external_plugins/serena", "code navigation MCP tools; uv/uvx and trust"),
    ("react-best-practices", "vercel-labs/agent-skills/skills/react-best-practices", "Vercel React and Next.js performance guidance"),
    ("react-native-skills", "vercel-labs/agent-skills/skills/react-native-skills", "Vercel React Native guidance"),
    ("web-design-guidelines", "vercel-labs/agent-skills/skills/web-design-guidelines", "Vercel web design and accessibility reviews"),
)


def source_for(name: str) -> str:
    return next((source for slug, source, _ in BUNDLES if slug == name), name)
