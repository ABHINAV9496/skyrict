"""Unit tests for the generic state machine (identity/core/state_machine.py)."""

from __future__ import annotations

import pytest

from identity.core.state_machine import InvalidTransitionError, StateMachine


@pytest.fixture
def machine() -> StateMachine:
    return StateMachine(
        {
            "invited": {"active"},
            "active": {"suspended"},
            "suspended": {"active"},
        },
        entity="membership",
    )


class TestStateMachineConstruction:
    def test_states_collects_all_known_states(self, machine: StateMachine) -> None:
        assert machine.states == {"invited", "active", "suspended"}

    def test_entity_label_used_in_errors(self, machine: StateMachine) -> None:
        assert machine.entity == "membership"


class TestStateMachineTransitions:
    def test_allowed_transition_passes(self, machine: StateMachine) -> None:
        assert machine.can_transition("invited", "active")
        machine.transition("invited", "active")

    def test_cycle_works(self, machine: StateMachine) -> None:
        machine.transition("active", "suspended")
        machine.transition("suspended", "active")

    def test_forbidden_transition_raises(self, machine: StateMachine) -> None:
        with pytest.raises(InvalidTransitionError) as exc:
            machine.transition("suspended", "invited")
        assert exc.value.current == "suspended"
        assert exc.value.target == "invited"
        assert exc.value.entity == "membership"

    def test_unknown_state_is_forbidden(self, machine: StateMachine) -> None:
        assert not machine.can_transition("ghost", "active")
        with pytest.raises(InvalidTransitionError):
            machine.transition("ghost", "active")

    def test_can_transition_never_raises(self, machine: StateMachine) -> None:
        assert not machine.can_transition("active", "invited")
        assert machine.can_transition("active", "suspended")


class TestStateMachineEdgeCases:
    def test_empty_target_set_is_dead_end(self) -> None:
        terminal = StateMachine({"done": set()})
        assert not terminal.can_transition("done", "done")
        with pytest.raises(InvalidTransitionError):
            terminal.transition("done", "done")

    def test_self_loop_allowed_only_if_declared(self) -> None:
        loop = StateMachine({"pending": {"pending", "done"}})
        loop.transition("pending", "pending")
        assert loop.can_transition("pending", "pending")
