"""Parser registry for managing trajectory parsers by ecosystem."""

from claude_vis.parsers.base import TrajectoryParser

_registry: dict[str, type[TrajectoryParser]] = {}


def register_parser(parser_cls: type[TrajectoryParser]) -> type[TrajectoryParser]:
    """
    Register a parser class by its ecosystem name.

    Can be used as a decorator::

        @register_parser
        class MyParser(TrajectoryParser):
            ecosystem_name = "my_ecosystem"
            ...

    Args:
        parser_cls: TrajectoryParser subclass to register.

    Returns:
        The same class, unmodified.
    """
    # Instantiate temporarily to read the ecosystem name
    name = parser_cls.__dict__.get("ecosystem_name")
    # If it's a property, not a string, or None, we need to instantiate
    if name is None or isinstance(name, property) or not isinstance(name, str):
        # Property-based — create a throwaway instance would be heavy,
        # so require ecosystem_name to also be overridable via class-level string
        instance = object.__new__(parser_cls)
        name = instance.ecosystem_name  # type: ignore[attr-defined]
    _registry[name] = parser_cls
    return parser_cls


def get_parser(ecosystem: str) -> TrajectoryParser:
    """
    Get a parser instance for the given ecosystem.

    Args:
        ecosystem: Ecosystem identifier (e.g. 'claude_code').

    Returns:
        A TrajectoryParser instance.

    Raises:
        KeyError: If no parser is registered for the ecosystem.
    """
    if ecosystem not in _registry:
        available = ", ".join(sorted(_registry.keys())) or "(none)"
        raise KeyError(
            f"No parser registered for ecosystem '{ecosystem}'. "
            f"Available: {available}"
        )
    return _registry[ecosystem]()


def list_ecosystems() -> list[str]:
    """Return all registered ecosystem names."""
    return sorted(_registry.keys())


# ---------------------------------------------------------------------------
# Auto-register built-in parsers
# ---------------------------------------------------------------------------

def _register_builtins() -> None:
    from claude_vis.parsers.claude_code import ClaudeCodeParser
    from claude_vis.parsers.codex import CodexParser

    register_parser(ClaudeCodeParser)
    register_parser(CodexParser)


_register_builtins()
