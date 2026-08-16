"""Generic finite state machine for core (ERP) domain lifecycles.

States are plain strings (enum values). A lifecycle declares its transition
table once; services validate every mutation through the machine so invalid
hops (e.g. approving a paid payroll run) fail fast instead of silently
corrupting state. Ported from ``services/identity`` (``identity/core/
state_machine.py``) so the two services share the same semantics.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


class InvalidTransitionError(Exception):
    """Raised when a lifecycle cannot move from one state to another."""

    def __init__(self, current: str, target: str, *, entity: str = "state") -> None:
        self.current = current
        self.target = target
        self.entity = entity
        super().__init__(f"Cannot transition {entity} from '{current}' to '{target}'")


class StateMachine:
    """Validates transitions between lifecycle states.

    Args:
        transitions: Mapping of current state -> iterable of allowed targets.
        entity: Human-readable lifecycle name for error messages.
    """

    def __init__(
        self,
        transitions: Mapping[str, Iterable[str]],
        *,
        entity: str = "state",
    ) -> None:
        self._transitions: dict[str, frozenset[str]] = {
            current: frozenset(targets) for current, targets in transitions.items()
        }
        self._entity = entity
        all_states: set[str] = set(self._transitions)
        for targets in self._transitions.values():
            all_states.update(targets)
        self._states = frozenset(all_states)

    @property
    def entity(self) -> str:
        return self._entity

    @property
    def states(self) -> frozenset[str]:
        return self._states

    def can_transition(self, current: str, target: str) -> bool:
        return current in self._transitions and target in self._transitions[current]

    def transition(self, current: str, target: str) -> None:
        if not self.can_transition(current, target):
            raise InvalidTransitionError(current, target, entity=self._entity)

    def __repr__(self) -> str:
        return f"StateMachine(entity={self._entity!r}, states={sorted(self._states)})"


__all__ = ["InvalidTransitionError", "StateMachine"]
