"""Unit tests for the SKY-99 aggregate report cache helpers.

``hash_report_key`` and the ``_json_safe``/``serialize_entity`` serializers are
pure functions (no DB); repository get/put/delete behavior is covered against
real Postgres in the integration suite (test_report_cache_repo.py).
"""

from __future__ import annotations

import dataclasses
import enum
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from core.features.finance.report_cache import (
    _json_safe,
    hash_report_key,
    serialize_entity,
)


class _Currency(enum.Enum):
    USD = "USD"


@dataclasses.dataclass(frozen=True)
class _MoneyValue:
    amount: Decimal
    currency: _Currency


@dataclasses.dataclass(frozen=True)
class _Bucket:
    label: str
    total: _MoneyValue


class TestHashReportKey:
    def test_deterministic_for_same_parts(self) -> None:
        assert hash_report_key("cashflow_projection", date(2026, 1, 1)) == hash_report_key(
            "cashflow_projection", date(2026, 1, 1)
        )

    def test_key_is_stable_sha256_hex(self) -> None:
        digest = hash_report_key("a", "b")
        assert isinstance(digest, str)
        assert len(digest) == 64
        int(digest, 16)  # must parse as hex

    def test_part_order_matters(self) -> None:
        assert hash_report_key("a", "b") != hash_report_key("b", "a")

    def test_accepts_uuids_and_enums(self) -> None:
        tid = uuid.uuid4()
        assert hash_report_key(tid, _Currency.USD) == hash_report_key(str(tid), str(_Currency.USD))


class TestSerializeEntity:
    def test_frozen_dataclass_becomes_nested_dict(self) -> None:
        entity = _Bucket(label="AR > 90", total=_MoneyValue(Decimal("1234.5600"), _Currency.USD))
        payload = serialize_entity(entity)
        assert payload == {
            "label": "AR > 90",
            "total": {"amount": "1234.5600", "currency": "USD"},
        }

    def test_primitive_scalar_wrapped(self) -> None:
        assert serialize_entity("just-a-string") == {"value": "just-a-string"}

    def test_decimal_preserved_as_string(self) -> None:
        assert _json_safe(Decimal("19.9900")) == "19.9900"

    def test_datetime_becomes_iso_string(self) -> None:
        now = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)
        assert _json_safe(now) == "2026-09-15T12:00:00+00:00"

    def test_uuid_becomes_string(self) -> None:
        tid = uuid.uuid4()
        assert _json_safe(tid) == str(tid)

    def test_dict_keys_are_recursed(self) -> None:
        payload = _json_safe({"money": Decimal("5.00")})
        assert payload == {"money": "5.00"}

    def test_none_and_primitives_pass_through(self) -> None:
        assert _json_safe(None) is None
        assert _json_safe(42) == 42
        assert _json_safe(True) is True
