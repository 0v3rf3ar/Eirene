"""Execution access, independent of the manual/auto/plan workflow."""


def full_access(config) -> bool:
    return config.get("permissions", "sandboxed") == "full-access"


def isolation(config) -> str:
    """Backend for hooks and MCP servers, which run only after explicit trust or enable."""
    if full_access(config):
        return "none"
    return str(config.get("execution_isolation", "auto"))


def isolate_network(config) -> bool:
    return not full_access(config) and bool(config.get("isolate_network", True))
