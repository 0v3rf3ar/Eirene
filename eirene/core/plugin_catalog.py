"""Portable bundles offered by /plugins browse and install shortcuts."""

OFFICIAL = "anthropics/claude-plugins-official"

# name, source, purpose/prerequisites; keep suggestions usable by the importer.
BUNDLES = (
    ("omniroute", "builtin:omniroute", "optional management MCP for an existing OmniRoute gateway; needs OmniRoute on PATH and trust"),
    ("ponytail", "DietrichGebert/ponytail", "minimal implementations; hooks need Node.js and trust"),
    ("superpowers", "builtin:superpowers", "design, plans, test-first work, debugging, review; bundled with Eirene; startup hook needs trust"),
    ("eirene-skills", "builtin:eirene-skills", "documents (Word, PDF, PowerPoint, Excel), design, frontend, testing, skill authoring; bundled with Eirene"),
    ("arena", "builtin:arena", "sub-agents compete over one task until one answer survives; bundled with Eirene; needs Python and a tool-capable provider"),
    ("obsidian", "builtin:obsidian", "Obsidian vault Markdown, Bases, Canvas and CLI; bundled with Eirene"),
    ("pr-review-toolkit", f"{OFFICIAL}/plugins/pr-review-toolkit", "PR review workflow and six specialist agent profiles"),
    ("feature-dev", f"{OFFICIAL}/plugins/feature-dev", "feature development with exploration, architecture, and review agents"),
    ("playwright", f"{OFFICIAL}/external_plugins/playwright", "browser MCP tools; Node.js/npx, browser dependencies, and trust"),
    ("serena", f"{OFFICIAL}/external_plugins/serena", "code navigation MCP tools; uv/uvx and trust"),
)


# Bundles whose files ship inside Eirene, adapted to it, in eirene/plugins/<name>.
SHIPPED = ("eirene-skills", "arena", "obsidian", "superpowers")
# Where /plugin update finds them in Eirene's repository.
SHIPPED_REPOSITORY_FOLDER = "eirene/plugins"


def source_for(name: str) -> str:
    if name.casefold() in ("omniroute", *SHIPPED):
        return f"builtin:{name.casefold()}"
    return next((source for slug, source, _ in BUNDLES if slug == name), name)
