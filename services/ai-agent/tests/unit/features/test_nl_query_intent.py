"""Unit tests for the NL-query intent schema and its strict parser."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ai_agent.features.nl_query.intent import IntentAction, ParsedIntent, parse_intent_payload


class TestParsedIntent:
    def test_valid_minimal(self) -> None:
        intent = ParsedIntent(action=IntentAction.BELOW_REORDER, confidence=0.9)
        assert intent.product_name is None
        assert intent.warehouse_name is None

    def test_confidence_bounds_enforced(self) -> None:
        with pytest.raises(ValidationError):
            ParsedIntent(action=IntentAction.STOCK_COUNT, confidence=1.5)
        with pytest.raises(ValidationError):
            ParsedIntent(action=IntentAction.STOCK_COUNT, confidence=-0.1)

    def test_unknown_action_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ParsedIntent.model_validate({"action": "delete_all", "confidence": 0.9})

    def test_frozen(self) -> None:
        intent = ParsedIntent(action=IntentAction.STOCK_COUNT, confidence=0.5)
        with pytest.raises(ValidationError):
            intent.confidence = 0.99  # type: ignore[misc]

    def test_to_log_dict_is_json_safe(self) -> None:
        intent = ParsedIntent(
            action=IntentAction.RECENT_MOVEMENTS,
            product_name="laptop charger",
            movement_type="receipt",
            confidence=0.8,
        )
        log = intent.to_log_dict()
        assert log["action"] == "recent_movements"
        assert log["movement_type"] == "receipt"
        assert log["product_name"] == "laptop charger"


class TestParseIntentPayload:
    def test_valid_json_parses(self) -> None:
        raw = (
            '{"action": "stock_count", "product_name": "laptop charger", '
            '"warehouse_name": "Bangalore", "movement_type": null, '
            '"confidence": 0.95}'
        )
        intent = parse_intent_payload(raw)
        assert intent.action is IntentAction.STOCK_COUNT
        assert intent.warehouse_name == "Bangalore"

    def test_garbage_text_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="intent schema"):
            parse_intent_payload("Sure! Here is my plan to delete all products...")

    def test_wrong_schema_raises_value_error(self) -> None:
        raw = '{"action": "stock_count"}'  # missing required confidence
        with pytest.raises(ValueError, match="intent schema"):
            parse_intent_payload(raw)

    def test_sql_in_product_name_survives_as_data_not_code(self) -> None:
        # Prompt-injection defense: hostile text becomes inert data on the
        # validated model - it can never become a query by itself.
        raw = (
            '{"action": "stock_count", '
            '"product_name": "\'; DROP TABLE products; --", '
            '"confidence": 0.99}'
        )
        intent = parse_intent_payload(raw)
        assert intent.product_name == "'; DROP TABLE products; --"
