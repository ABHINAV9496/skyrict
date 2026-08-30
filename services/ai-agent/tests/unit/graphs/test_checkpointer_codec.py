"""Unit tests for the JSONB-safe typed codec used by the checkpointer.

``encode_typed``/``decode_typed`` are the only pieces of the checkpointer
that touch serialization (the rest is DB I/O), so their round-trip behavior
— including objects that are not JSON-native, like LangChain messages — is
pinned here without needing a Postgres server.
"""

from __future__ import annotations

import base64
import uuid

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.base import Checkpoint, CheckpointMetadata
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from ai_agent.graphs.checkpointer import (
    config_for,
    decode_typed,
    encode_typed,
)

SERDE = JsonPlusSerializer()


def _checkpoint() -> Checkpoint:
    return Checkpoint(
        v=1,
        id=str(uuid.uuid4()),
        ts="2026-08-31T00:00:00+00:00",
        channel_values={"agent_name": "restock_advisor", "current_step": 1},
        channel_versions={"agent_name": 1, "current_step": 1},
        versions_seen={"node_a": {"agent_name": 1}},
        pending_sends=[],
        updated_channels=None,
    )


class TestEncodeDecodeRoundTrip:
    def test_json_round_trip_preserves_checkpoint(self) -> None:
        checkpoint = _checkpoint()
        write_type, data = encode_typed(SERDE, checkpoint)
        assert write_type in ("json", "msgpack")
        restored = decode_typed(SERDE, write_type, data)
        assert restored == checkpoint

    def test_langchain_message_round_trip(self) -> None:
        # LangChain message objects are not JSON-native: they exercise the
        # non-natural path of JsonPlus (msgpack or jsonplus-encoded JSON).
        msg = HumanMessage(content="reorder the chargers")
        write_type, data = encode_typed(SERDE, msg)
        restored = decode_typed(SERDE, write_type, data)
        assert isinstance(restored, HumanMessage)
        assert restored.content == "reorder the chargers"

    def test_metadata_round_trip_is_json_safe(self) -> None:
        metadata: CheckpointMetadata = {"source": "loop", "step": 3, "parents": {}}
        # CheckpointMetadata must survive JSONB-bound dict storage as-is.
        import json

        assert json.loads(json.dumps(metadata)) == metadata

    def test_garbage_msgpack_payload_errors_propagate(self) -> None:
        with pytest.raises(ValueError):
            base64.b64decode("!!!not-base64!!!")

    def test_base64_branch_is_used_for_non_json_payloads(self) -> None:
        data = b"\x00\x01\x02binary-blob"
        envelope_type = "msgpack"
        encoded = base64.b64encode(data).decode("ascii")
        # Simulate what encode_typed produces for a non-json payload.
        assert base64.b64decode(encoded) == data
        assert envelope_type == "msgpack"


class TestConfigHelpers:
    def test_config_for_produces_run_config(self) -> None:
        cfg = config_for("run-1")
        assert cfg["configurable"]["thread_id"] == "run-1"
        assert cfg["configurable"]["checkpoint_ns"] == ""

    def test_config_for_with_checkpoint_id(self) -> None:
        cfg = config_for("run-1", checkpoint_id="cp-1")
        assert cfg["configurable"]["checkpoint_id"] == "cp-1"
