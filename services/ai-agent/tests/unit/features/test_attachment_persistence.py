"""Unit tests for chat attachment persistence (SKY-60 attachment durability).

Covers the local attachment storage backend, the base64/size guards in the
conversations router helper, and the public metadata serialization that hides
the internal storage key.
"""

from __future__ import annotations

import base64
import uuid
from typing import Any

import pytest

from ai_agent import models  # noqa: F401  # registers every model on Base.metadata
from ai_agent.api.v1.routers.conversations import _store_attachments
from ai_agent.db.conversation_repository import _message_to_dict
from ai_agent.features.attachments.storage import LocalAttachmentStorage
from ai_agent.models.ai_conversation_message import AiConversationMessage


class TestLocalAttachmentStorage:
    async def test_put_get_roundtrip(self, tmp_path) -> None:
        storage = LocalAttachmentStorage(tmp_path)
        key = f"{uuid.uuid4()}/{uuid.uuid4()}/{uuid.uuid4()}"

        await storage.put(key, b"hello world", "text/plain")
        assert await storage.get(key) == b"hello world"

    async def test_missing_key_returns_none(self, tmp_path) -> None:
        storage = LocalAttachmentStorage(tmp_path)
        missing = f"{uuid.uuid4()}/{uuid.uuid4()}/{uuid.uuid4()}"
        assert await storage.get(missing) is None

    async def test_delete_removes_blob(self, tmp_path) -> None:
        storage = LocalAttachmentStorage(tmp_path)
        key = f"{uuid.uuid4()}/{uuid.uuid4()}/{uuid.uuid4()}"
        await storage.put(key, b"data", None)
        assert await storage.get(key) == b"data"
        await storage.delete(key)
        assert await storage.get(key) is None

    async def test_parent_directories_created(self, tmp_path) -> None:
        storage = LocalAttachmentStorage(tmp_path / "nested" / "root")
        key = f"{uuid.uuid4()}/{uuid.uuid4()}/{uuid.uuid4()}"
        await storage.put(key, b"x", None)
        assert await storage.get(key) == b"x"

    async def test_traversal_key_rejected(self, tmp_path) -> None:
        storage = LocalAttachmentStorage(tmp_path)
        with pytest.raises(ValueError):
            await storage.put("../escape", b"x", None)


class TestStoreAttachments:
    def _attachment(self, *, data: bytes, name: str = "report.pdf") -> Any:
        return type(
            "_Att",
            (),
            {
                "id": f"att-{uuid.uuid4()}",
                "name": name,
                "type": "application/pdf",
                "size": len(data),
                "base64": base64.b64encode(data).decode(),
            },
        )()

    async def test_stores_blobs_and_returns_metadata(self, tmp_path) -> None:
        storage = LocalAttachmentStorage(tmp_path)
        tenant_id = uuid.uuid4()
        conversation_id = uuid.uuid4()
        payload = [self._attachment(data=b"pdf-bytes")]

        metadata = await _store_attachments(
            storage=storage,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            attachments=payload,
        )

        assert len(metadata) == 1
        entry = metadata[0]
        assert entry["id"] == payload[0].id
        assert entry["name"] == "report.pdf"
        assert entry["type"] == "application/pdf"
        assert entry["size"] == len(b"pdf-bytes")
        # Server-side storage key is a fresh UUID, never the client id.
        assert entry["storage_key"] != payload[0].id
        uuid.UUID(entry["storage_key"])  # parses as a UUID
        # The blob landed in storage under the tenant/annotation key.
        blob = await storage.get(
            f"{tenant_id}/{conversation_id}/{entry['storage_key']}",
        )
        assert blob == b"pdf-bytes"

    async def test_invalid_base64_rejected(self, tmp_path) -> None:
        storage = LocalAttachmentStorage(tmp_path)
        bad = self._attachment(data=b"raw")
        bad.base64 = "not!base64!!"

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await _store_attachments(
                storage=storage,
                tenant_id=uuid.uuid4(),
                conversation_id=uuid.uuid4(),
                attachments=[bad],
            )
        assert exc.value.status_code == 422

    async def test_oversized_attachment_rejected(self, tmp_path, monkeypatch) -> None:
        storage = LocalAttachmentStorage(tmp_path)
        from ai_agent.core.config import settings

        monkeypatch.setattr(settings, "ATTACHMENT_MAX_BYTES", 10)
        big = self._attachment(data=b"x" * 11)

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await _store_attachments(
                storage=storage,
                tenant_id=uuid.uuid4(),
                conversation_id=uuid.uuid4(),
                attachments=[big],
            )
        assert exc.value.status_code == 413

    async def test_storage_failure_raises(self, tmp_path) -> None:
        class _FailingStorage:
            name = "failing"

            async def put(self, key: str, data: bytes, content_type: str | None) -> None:
                raise OSError("disk full")

            async def get(self, key: str) -> bytes | None:
                return None

            async def delete(self, key: str) -> None:
                pass

        payload = [self._attachment(data=b"x" * 5)]
        with pytest.raises(OSError):
            await _store_attachments(
                storage=_FailingStorage(),  # type: ignore[arg-type]
                tenant_id=uuid.uuid4(),
                conversation_id=uuid.uuid4(),
                attachments=payload,
            )


class TestMessageSerialization:
    def test_message_to_dict_exposes_public_metadata_only(self) -> None:
        storage_id = str(uuid.uuid4())
        row = AiConversationMessage(
            tenant_id=uuid.uuid4(),
            id=uuid.uuid4(),
            conversation_id=uuid.uuid4(),
            role="user",
            content="check this",
            attachments=[
                {
                    "id": "att-img-1",
                    "name": "chart.png",
                    "type": "image/png",
                    "size": 1234,
                    "storage_key": storage_id,
                }
            ],
        )
        row.created_at = None

        data = _message_to_dict(row)

        assert data["attachments"] == [
            {
                "id": "att-img-1",
                "name": "chart.png",
                "type": "image/png",
                "size": 1234,
            }
        ]
        # The internal object key must never leak through the public API.
        assert "storage_key" not in data["attachments"][0]

    def test_message_to_dict_defaults_to_empty_list(self) -> None:
        row = AiConversationMessage(
            tenant_id=uuid.uuid4(),
            id=uuid.uuid4(),
            conversation_id=uuid.uuid4(),
            role="agent",
            content="ok",
        )
        row.created_at = None
        assert _message_to_dict(row)["attachments"] == []
