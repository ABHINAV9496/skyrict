"""State machine tests — employee, leave request, and payroll run lifecycles.

Pure logic: the transition tables live in the services (docs/hr-payroll.md
§3.3 / §4.10) and configure the shared ``StateMachine`` from
``core.core.state_machine`` (ported from identity). No database.
"""

from __future__ import annotations

import pytest

from core.core.constants import EmploymentStatus, LeaveRequestStatus, PayrollRunStatus
from core.core.state_machine import InvalidTransitionError, StateMachine
from core.features.hr.service import _EMPLOYEE_MACHINE, _LEAVE_MACHINE
from core.features.payroll.service import _RUN_MACHINE

pytestmark = pytest.mark.unit


class TestStateMachineCore:
    def test_states_are_derived_from_transition_table(self) -> None:
        machine = StateMachine({"a": ("b",), "b": ()}, entity="thing")
        assert machine.states == frozenset({"a", "b"})

    def test_transition_valid(self) -> None:
        machine = StateMachine({"a": ("b",)}, entity="thing")
        machine.transition("a", "b")

    def test_transition_invalid_raises_with_entity_and_hop(self) -> None:
        machine = StateMachine({"a": ("b",)}, entity="thing")
        with pytest.raises(InvalidTransitionError) as excinfo:
            machine.transition("b", "a")
        assert excinfo.value.current == "b"
        assert excinfo.value.target == "a"
        assert excinfo.value.entity == "thing"

    def test_can_transition(self) -> None:
        machine = StateMachine({"a": ("b", "c")}, entity="thing")
        assert machine.can_transition("a", "b")
        assert machine.can_transition("a", "c")
        assert not machine.can_transition("a", "a")
        assert not machine.can_transition("b", "a")

    def test_terminal_state_has_no_targets(self) -> None:
        machine = StateMachine({"a": ("b",), "b": ()}, entity="thing")
        assert not machine.can_transition("b", "a")
        with pytest.raises(InvalidTransitionError):
            machine.transition("b", "a")


class TestEmployeeMachine:
    def test_active_to_on_leave(self) -> None:
        _EMPLOYEE_MACHINE.transition(EmploymentStatus.ACTIVE, EmploymentStatus.ON_LEAVE)

    def test_on_leave_to_active(self) -> None:
        _EMPLOYEE_MACHINE.transition(EmploymentStatus.ON_LEAVE, EmploymentStatus.ACTIVE)

    def test_active_to_terminated(self) -> None:
        _EMPLOYEE_MACHINE.transition(EmploymentStatus.ACTIVE, EmploymentStatus.TERMINATED)

    def test_on_leave_to_terminated(self) -> None:
        _EMPLOYEE_MACHINE.transition(EmploymentStatus.ON_LEAVE, EmploymentStatus.TERMINATED)

    def test_terminated_is_terminal(self) -> None:
        with pytest.raises(InvalidTransitionError):
            _EMPLOYEE_MACHINE.transition(EmploymentStatus.TERMINATED, EmploymentStatus.ACTIVE)
        with pytest.raises(InvalidTransitionError):
            _EMPLOYEE_MACHINE.transition(EmploymentStatus.TERMINATED, EmploymentStatus.ON_LEAVE)


class TestLeaveMachine:
    def test_pending_to_approved(self) -> None:
        _LEAVE_MACHINE.transition(LeaveRequestStatus.PENDING, LeaveRequestStatus.APPROVED)

    def test_pending_to_rejected(self) -> None:
        _LEAVE_MACHINE.transition(LeaveRequestStatus.PENDING, LeaveRequestStatus.REJECTED)

    def test_pending_to_cancelled(self) -> None:
        _LEAVE_MACHINE.transition(LeaveRequestStatus.PENDING, LeaveRequestStatus.CANCELLED)

    def test_approved_to_cancelled(self) -> None:
        _LEAVE_MACHINE.transition(LeaveRequestStatus.APPROVED, LeaveRequestStatus.CANCELLED)

    def test_rejected_is_terminal(self) -> None:
        with pytest.raises(InvalidTransitionError):
            _LEAVE_MACHINE.transition(LeaveRequestStatus.REJECTED, LeaveRequestStatus.APPROVED)

    def test_cancelled_is_terminal(self) -> None:
        with pytest.raises(InvalidTransitionError):
            _LEAVE_MACHINE.transition(LeaveRequestStatus.CANCELLED, LeaveRequestStatus.APPROVED)

    def test_approved_cannot_be_rejected(self) -> None:
        with pytest.raises(InvalidTransitionError):
            _LEAVE_MACHINE.transition(LeaveRequestStatus.APPROVED, LeaveRequestStatus.REJECTED)


class TestPayrollRunMachine:
    def test_draft_to_computed(self) -> None:
        _RUN_MACHINE.transition(PayrollRunStatus.DRAFT, PayrollRunStatus.COMPUTED)

    def test_computed_to_approved(self) -> None:
        _RUN_MACHINE.transition(PayrollRunStatus.COMPUTED, PayrollRunStatus.APPROVED)

    def test_computed_recompute_is_self_transition(self) -> None:
        _RUN_MACHINE.transition(PayrollRunStatus.COMPUTED, PayrollRunStatus.COMPUTED)

    def test_approved_to_paid(self) -> None:
        _RUN_MACHINE.transition(PayrollRunStatus.APPROVED, PayrollRunStatus.PAID)

    def test_void_from_draft(self) -> None:
        _RUN_MACHINE.transition(PayrollRunStatus.DRAFT, PayrollRunStatus.VOID)

    def test_void_from_computed(self) -> None:
        _RUN_MACHINE.transition(PayrollRunStatus.COMPUTED, PayrollRunStatus.VOID)

    def test_void_from_approved(self) -> None:
        _RUN_MACHINE.transition(PayrollRunStatus.APPROVED, PayrollRunStatus.VOID)

    def test_paid_cannot_be_voided(self) -> None:
        with pytest.raises(InvalidTransitionError):
            _RUN_MACHINE.transition(PayrollRunStatus.PAID, PayrollRunStatus.VOID)

    def test_paid_is_terminal(self) -> None:
        with pytest.raises(InvalidTransitionError):
            _RUN_MACHINE.transition(PayrollRunStatus.PAID, PayrollRunStatus.COMPUTED)

    def test_draft_cannot_be_approved_directly(self) -> None:
        with pytest.raises(InvalidTransitionError):
            _RUN_MACHINE.transition(PayrollRunStatus.DRAFT, PayrollRunStatus.APPROVED)

    def test_computed_cannot_skip_to_paid(self) -> None:
        with pytest.raises(InvalidTransitionError):
            _RUN_MACHINE.transition(PayrollRunStatus.COMPUTED, PayrollRunStatus.PAID)
