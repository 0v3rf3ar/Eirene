"""Execution access, independent of the manual/auto/plan workflow."""


def full_access(config) -> bool:
    return config.get("permissions", "sandboxed") == "full-access"


def isolation(config) -> str:
    """Backend for hooks and MCP servers, which run only after explicit trust or enable."""
    if full_access(config):
        return "none"
    chosen = str(config.get("execution_isolation", "auto"))
    from .platforms import is_termux
    # Termux has no isolation backend; as with its commands, consent replaces a sandbox.
    return "none" if chosen == "auto" and is_termux() else chosen


def isolate_network(config) -> bool:
    return not full_access(config) and bool(config.get("isolate_network", True))
