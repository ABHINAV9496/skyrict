"""CLI surface tests - command registration and naming (SKY-58)."""

from collections.abc import Callable
from typing import Any

from ai_agent.cli import app


def _registered() -> dict[str, Callable[..., Any]]:
    """Map callback function name -> callable for every registered command."""
    commands: dict[str, Callable[..., Any]] = {}
    for cmd in app.registered_commands:
        if cmd.callback is not None:
            commands[cmd.callback.__name__] = cmd.callback
    return commands


def test_eval_command_is_registered_as_eval() -> None:
    """The RAGAS gate is dispatched as `ai-agent eval` (not the builtin name)."""
    names = {cmd.name for cmd in app.registered_commands}
    assert "eval" in names
    # The explicit name belongs to the `evaluate` callback, so the builtin
    # is never shadowed in the CLI namespace.
    eval_cmd = next(cmd for cmd in app.registered_commands if cmd.name == "eval")
    assert eval_cmd.callback is not None
    assert eval_cmd.callback.__name__ == "evaluate"


def test_expected_command_surface_registered() -> None:
    """Every operational command is reachable via its CLI name."""
    commands = _registered()
    assert {"serve", "migrate", "ingest", "evaluate", "sweep_caches"} <= set(commands)


def test_eval_command_accepts_threshold_flags() -> None:
    """The gate thresholds are tunable from the command line (CI overrides)."""
    import inspect

    names = set(inspect.signature(_registered()["evaluate"]).parameters)
    for flag in ("faithfulness", "answer_relevancy", "context_precision", "context_recall"):
        assert flag in names, f"missing threshold flag: --{flag}"


def test_inventory_reindex_subcommand_registered() -> None:
    """The SKY-70 snapshot rebuild is dispatched as `ai-agent inventory reindex`."""
    from ai_agent.cli import inventory_app

    names = {cmd.name for cmd in inventory_app.registered_commands}
    assert "reindex" in names
    reindex_cmd = next(cmd for cmd in inventory_app.registered_commands if cmd.name == "reindex")
    assert reindex_cmd.callback is not None
    assert reindex_cmd.callback.__name__ == "inventory_reindex"
