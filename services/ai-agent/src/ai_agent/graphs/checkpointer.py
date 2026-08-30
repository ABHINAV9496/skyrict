"""Async SQLAlchemy checkpointer for LangGraph (SKY-59, AGT-001).

Implements ``langgraph.checkpoint.base.BaseCheckpointSaver`` against
``graph_checkpoints`` / ``graph_checkpoint_writes`` (migration 0008) so the
ai-agent service needs no psycopg or msgpack sidecar — every payload travels
as JSONB.

Serialization
  LangGraph checkpoints and task writes are arbitrary objects (LangChain
  message objects, etc.). The stock Postgres checkpointer keeps the original
  bytes plus a type tag; JSONB forces the same envelope
  ``{"type": "json"|"msgpack", "data": ...}``, where ``data`` is the
  :meth:`SerializerProtocol.dumps_typed` output decoded to text for the
  ``json`` type (msgpack blobs are base64). ``metadata`` is JSON-safe after
  the runtime's ``get_serializable_checkpoint_metadata`` sanitization and is
  stored directly, mirroring the official Postgres saver.

Tenant scoping
  Every operation opens its own session via ``async_session_factory`` so the
  request-scoped ``TenantContext`` (see db/session.py ``after_begin`` hook)
  pins ``app.current_tenant_id`` before the first statement. The RLS policies
  on both tables then bound every read/write to the current tenant. Any graph
  invocation/resume therefore runs inside one request's tenant context —
  the saver can never read or overwrite another tenant's run.

Threads
  ``graph_run_id`` is our canonical thread id: the runtime seeds a fresh uuid
  per run and the LangGraph ``thread_id`` config key is mapped to it in
  :func:`config_for` (the runtime layer builds run configs through it).
"""

from __future__ import annotations

import asyncio
import base64
import uuid
from typing import TYPE_CHECKING, Any, cast

from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ai_agent.core.tenant_context import TenantContext
from ai_agent.db.session import async_session_factory
from ai_agent.models.graph_checkpoint import (
    GraphCheckpointModel,
    GraphCheckpointWriteModel,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.serde.base import SerializerProtocol


# ---------------------------------------------------------------------------
# JSONB-safe typed serialization (pure, unit-testable)
# ---------------------------------------------------------------------------
def encode_typed(serde: SerializerProtocol, value: Any) -> tuple[str, str]:
    """Serialize a value into a JSONB-safe ``(type, data)`` envelope pair."""
    write_type, blob = serde.dumps_typed(value)
    if write_type == "json":
        return write_type, blob.decode("utf-8")
    return write_type, base64.b64encode(blob).decode("ascii")


def decode_typed(serde: SerializerProtocol, write_type: str, data: str) -> Any:
    """Reverse :func:`encode_typed` — ``data`` is text (json) or base64."""
    blob = data.encode("utf-8") if write_type == "json" else base64.b64decode(data)
    return serde.loads_typed((write_type, blob))


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------
def _require_thread_id(config: RunnableConfig) -> str:
    """Pull the ``thread_id`` (= our graph_run_id) from a run config."""
    configurable = config.get("configurable") or {}
    thread_id = configurable.get("thread_id")
    if not isinstance(thread_id, str):
        raise ValueError("checkpointer config requires a string 'thread_id'")
    return thread_id


def _checkpoint_ns(config: RunnableConfig) -> str:
    configurable = config.get("configurable") or {}
    return str(configurable.get("checkpoint_ns") or "")


def _checkpoint_id(config: RunnableConfig) -> str | None:
    configurable = config.get("configurable") or {}
    checkpoint_id = configurable.get("checkpoint_id")
    return checkpoint_id if isinstance(checkpoint_id, str) else None


def _current_tenant() -> uuid.UUID:
    """The request tenant — MUST be set before any graph run starts."""
    return uuid.UUID(TenantContext.get())


def config_for(thread_id: str, checkpoint_id: str | None = None) -> RunnableConfig:
    """Build the run config the runtime passes to a graph (thread = run id)."""
    configurable: dict[str, Any] = {"thread_id": thread_id, "checkpoint_ns": ""}
    if checkpoint_id is not None:
        configurable["checkpoint_id"] = checkpoint_id
    return {"configurable": configurable}


class SqlAlchemyCheckpointSaver(BaseCheckpointSaver[int]):
    """Tenant-scoped, restart-safe checkpointer backed by Postgres JSONB."""

    @property
    def config_specs(self) -> list[dict[str, Any]]:
        return [
            {"name": "thread_id", "type": "string"},
            {"name": "checkpoint_ns", "type": "string", "default": ""},
        ]

    # --- async interface (used by every ai invoke/resume in the service) -------

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        tenant_id = _current_tenant()
        run_id = uuid.UUID(_require_thread_id(config))
        checkpoint_id = _checkpoint_id(config)

        async with async_session_factory() as session:
            stmt = select(GraphCheckpointModel).where(
                GraphCheckpointModel.tenant_id == tenant_id,
                GraphCheckpointModel.graph_run_id == run_id,
            )
            if checkpoint_id is not None:
                stmt = stmt.where(GraphCheckpointModel.checkpoint_id == uuid.UUID(checkpoint_id))
            else:
                stmt = stmt.order_by(
                    GraphCheckpointModel.updated_at.desc(),
                    GraphCheckpointModel.id.desc(),
                ).limit(1)
            checkpoint_row = (await session.execute(stmt)).scalar_one_or_none()
            if checkpoint_row is None:
                return None

            writes_result = await session.execute(
                select(GraphCheckpointWriteModel)
                .where(
                    GraphCheckpointWriteModel.tenant_id == tenant_id,
                    GraphCheckpointWriteModel.graph_run_id == run_id,
                    GraphCheckpointWriteModel.checkpoint_id == checkpoint_row.checkpoint_id,
                )
                .order_by(GraphCheckpointWriteModel.idx.asc())
            )
            writes_rows = writes_result.scalars().all()

        checkpoint = cast(
            "Checkpoint",
            decode_typed(
                self.serde,
                checkpoint_row.state["type"],
                checkpoint_row.state["data"],
            ),
        )
        pending_writes = [
            (
                w.task_id,
                w.channel,
                decode_typed(self.serde, w.value["type"], w.value["data"]),
            )
            for w in writes_rows
        ]
        thread_id = str(checkpoint_row.graph_run_id)
        return CheckpointTuple(
            config=config_for(thread_id, str(checkpoint_row.checkpoint_id)),
            checkpoint=checkpoint,
            metadata=cast("CheckpointMetadata", checkpoint_row.metadata_json),
            parent_config=(
                config_for(thread_id, str(checkpoint_row.parent_checkpoint_id))
                if checkpoint_row.parent_checkpoint_id is not None
                else None
            ),
            pending_writes=pending_writes,
        )

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: Any,
    ) -> RunnableConfig:
        tenant_id = _current_tenant()
        run_id = uuid.UUID(_require_thread_id(config))
        checkpoint_id = uuid.UUID(checkpoint["id"])
        parent_id = _checkpoint_id(config)
        write_type, data = encode_typed(self.serde, checkpoint)
        state_envelope = {"type": write_type, "data": data}
        step = int(metadata.get("step", 0) or 0)

        async with async_session_factory() as session:
            await session.execute(
                pg_insert(GraphCheckpointModel)
                .values(
                    tenant_id=tenant_id,
                    id=uuid.uuid4(),
                    graph_run_id=run_id,
                    checkpoint_id=checkpoint_id,
                    parent_checkpoint_id=(uuid.UUID(parent_id) if parent_id is not None else None),
                    checkpoint_type=write_type,
                    state=state_envelope,
                    metadata_json=metadata,
                    step=step,
                )
                .on_conflict_do_update(
                    constraint="uq_graph_checkpoints_run_checkpoint",
                    set_={
                        "parent_checkpoint_id": (
                            uuid.UUID(parent_id) if parent_id is not None else None
                        ),
                        "checkpoint_type": write_type,
                        "state": state_envelope,
                        "metadata_json": metadata,
                        "step": step,
                    },
                )
            )
            await session.commit()

        return {
            **config,
            "configurable": {
                **config.get("configurable", {}),
                "checkpoint_id": str(checkpoint_id),
            },
        }

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        tenant_id = _current_tenant()
        run_id = uuid.UUID(_require_thread_id(config))
        checkpoint_ref = _checkpoint_id(config)
        if checkpoint_ref is None:
            raise ValueError("aput_writes requires a checkpoint_id in config")
        checkpoint_uuid = uuid.UUID(checkpoint_ref)

        rows: list[GraphCheckpointWriteModel] = []
        for idx, (channel, value) in enumerate(writes):
            write_type, data = encode_typed(self.serde, value)
            rows.append(
                GraphCheckpointWriteModel(
                    tenant_id=tenant_id,
                    id=uuid.uuid4(),
                    graph_run_id=run_id,
                    checkpoint_id=checkpoint_uuid,
                    task_id=task_id,
                    task_path=task_path,
                    # Special writes carry a sentinel channel name
                    # (__error__/__interrupt__/__resume__/__scheduled__); map
                    # those to negative indices so they never collide with
                    # regular writes (same mapping as the stock saver).
                    idx=WRITES_IDX_MAP.get(channel, idx),
                    channel=channel,
                    write_type=write_type,
                    value={"type": write_type, "data": data},
                )
            )

        async with async_session_factory() as session:
            # Replace any prior writes for the same task slot in one transaction
            # (resume rewrites the pending ledger for the current checkpoint).
            await session.execute(
                delete(GraphCheckpointWriteModel).where(
                    GraphCheckpointWriteModel.tenant_id == tenant_id,
                    GraphCheckpointWriteModel.graph_run_id == run_id,
                    GraphCheckpointWriteModel.checkpoint_id == checkpoint_uuid,
                    GraphCheckpointWriteModel.task_id == task_id,
                    GraphCheckpointWriteModel.task_path == task_path,
                )
            )
            if rows:
                session.add_all(rows)
            await session.commit()

    async def adelete_thread(self, thread_id: str) -> None:
        tenant_id = _current_tenant()
        run_id = uuid.UUID(thread_id)
        async with async_session_factory() as session:
            # The composite FK cascades to graph_checkpoint_writes.
            await session.execute(
                delete(GraphCheckpointModel).where(
                    GraphCheckpointModel.tenant_id == tenant_id,
                    GraphCheckpointModel.graph_run_id == run_id,
                )
            )
            await session.commit()

    # --- sync interface (safety net for sync tooling; service is async-only) ----

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        return asyncio.run(self.aget_tuple(config))

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: Any,
    ) -> RunnableConfig:
        return asyncio.run(self.aput(config, checkpoint, metadata, new_versions))

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        asyncio.run(self.aput_writes(config, writes, task_id, task_path))

    def delete_thread(self, thread_id: str) -> None:
        asyncio.run(self.adelete_thread(thread_id))
