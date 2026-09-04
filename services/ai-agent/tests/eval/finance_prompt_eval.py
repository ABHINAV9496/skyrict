"""Prompt eval registry for finance AI draft-entry (A2) cases (FIN-AI-001).

Plain data — no network, no pytest assertions. CI can import ``cases`` and
``count()`` to drive the deployed scorer harness. Each case is a dict with:

    id                  unique case identifier
    description         free-text transaction description
    accounts            list of {"code", "name"} dicts (the chart)
    expected_min_lines  minimum lines the LLM should produce
    expected_balanced   whether total debits should equal total credits
"""

from __future__ import annotations

_CHART = [
    {"code": "1000", "name": "Cash"},
    {"code": "1100", "name": "Accounts Receivable"},
    {"code": "1500", "name": "Equipment"},
    {"code": "5000", "name": "Rent Expense"},
    {"code": "5100", "name": "Utilities Expense"},
    {"code": "5200", "name": "Salaries Expense"},
    {"code": "4000", "name": "Revenue"},
    {"code": "2000", "name": "Accounts Payable"},
    {"code": "3000", "name": "Owner Equity"},
    {"code": "6000", "name": "Office Supplies Expense"},
]

cases: list[dict[str, object]] = [
    {
        "id": "A2-001",
        "description": "Paid cash for monthly office rent $2,000",
        "accounts": _CHART,
        "expected_min_lines": 2,
        "expected_balanced": True,
    },
    {
        "id": "A2-002",
        "description": "Purchased equipment for $5,000, paid by bank transfer",
        "accounts": _CHART,
        "expected_min_lines": 2,
        "expected_balanced": True,
    },
    {
        "id": "A2-003",
        "description": "Received payment of $3,500 from customer Acme Corp for invoice INV-042",
        "accounts": _CHART,
        "expected_min_lines": 2,
        "expected_balanced": True,
    },
    {
        "id": "A2-004",
        "description": "Paid $1,200 electricity bill and $800 water bill from cash",
        "accounts": _CHART,
        "expected_min_lines": 3,
        "expected_balanced": True,
    },
    {
        "id": "A2-005",
        "description": "Owner invested $10,000 into the business",
        "accounts": _CHART,
        "expected_min_lines": 2,
        "expected_balanced": True,
    },
    {
        "id": "A2-006",
        "description": "Paid salaries of $8,500 to employees for January",
        "accounts": _CHART,
        "expected_min_lines": 2,
        "expected_balanced": True,
    },
    {
        "id": "A2-007",
        "description": "Bought office supplies for $150 cash",
        "accounts": _CHART,
        "expected_min_lines": 2,
        "expected_balanced": True,
    },
    {
        "id": "A2-008",
        "description": "Invoiced customer Beta Inc $4,200 for consulting services",
        "accounts": _CHART,
        "expected_min_lines": 2,
        "expected_balanced": True,
    },
    {
        "id": "A2-009",
        "description": "Paid $600 for annual software subscription",
        "accounts": _CHART,
        "expected_min_lines": 2,
        "expected_balanced": True,
    },
    {
        "id": "A2-010",
        "description": "Lunch with client",
        "accounts": _CHART,
        "expected_min_lines": 0,
        "expected_balanced": False,
    },
    {
        "id": "A2-011",
        "description": "Miscellaneous adjustment",
        "accounts": _CHART,
        "expected_min_lines": 0,
        "expected_balanced": False,
    },
    {
        "id": "A2-012",
        "description": "Received cash $500 and paid supplier $300 for restocking inventory",
        "accounts": _CHART,
        "expected_min_lines": 3,
        "expected_balanced": True,
    },
    {
        "id": "A2-013",
        "description": "Paid $250 for office supplies and $175 for utilities from bank account",
        "accounts": _CHART,
        "expected_min_lines": 3,
        "expected_balanced": True,
    },
    {
        "id": "A2-014",
        "description": "Paid \u00a31,500 for UK consulting services",
        "accounts": _CHART,
        "expected_min_lines": 2,
        "expected_balanced": True,
    },
    {
        "id": "A2-015",
        "description": "Paid \u20b950,000 for annual office lease in Mumbai",
        "accounts": _CHART,
        "expected_min_lines": 2,
        "expected_balanced": True,
    },
    {
        "id": "A2-016",
        "description": "Received \u20ac3,000 from European customer for January invoice",
        "accounts": _CHART,
        "expected_min_lines": 2,
        "expected_balanced": True,
    },
    {
        "id": "A2-017",
        "description": "Paid rent $2,000 and utilities $400 and office supplies $120",
        "accounts": _CHART,
        "expected_min_lines": 4,
        "expected_balanced": True,
    },
    {
        "id": "A2-018",
        "description": "The quarterly review went well",
        "accounts": _CHART,
        "expected_min_lines": 0,
        "expected_balanced": False,
    },
]


def count() -> int:
    """Return the number of eval cases in this registry."""
    return len(cases)
