"""Declarative PipelineSpec: the contract for one module-group Bronze landing.

The pipeline spec is read by the carrier from ``fabric/pipelines/*.pipeline.json``.
It carries only **what** to extract and **how** to land it:

* ``a schema`` `what` exactly — source connection ref (never inline creds —
  the repo rule is creds live in catalog / Key Vault), module group, ordered
  source tables (parents before children, so Bronze FK integrity holds by
  construction).
* ``schedule_cron`` — the declarative cadence (a runbook/scheduler concern,
  not a carrier concern).

Identifiers (``watermark_col``, ``pk_col``) are drawn from the *trusted*
declarative spec — never user input; all boundary **values** are bound
parameters. The incremental semantics are owned by :mod:`skyrict_fabric.watermark`.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from skyrict_fabric.watermark import ExtractMode

__all__ = ["PipelineSpec", "SourceTable"]


class SourceTable(BaseModel):
    """One source table landed to Bronze.

    ``bronze_alias``: optional Bronze name override (defaults to ``name``).
    ``watermark_col``: the monotonically increasing column used for incremental
    extraction (typically ``updated_at``). ``pk_col``: the source primary key,
    used for the exact boundary tie-break and as the Bronze upsert key. ``mode``:
    the **initial** extract mode — a table's first load is always ``full`` (parity
    from zero); it flips to ``incremental`` once a HWM exists.
    """

    name: str
    bronze_alias: str | None = None
    watermark_col: str = Field(default="updated_at")
    pk_col: str = "id"
    mode: ExtractMode = ExtractMode.FULL


class PipelineSpec(BaseModel):
    """A module-group pipeline: source connection + ordered source tables.

    A pipeline is the unit of scheduling and parity in Bronze. Each pipeline
    belongs to exactly one module group (CRM/sales, finance, inventory,
    HR/Payroll, references) and lists its source tables in dependency order —
    parents before children — so Bronze FK integrity holds by construction and
    parity is provable per boundary.
    """

    name: str
    module_group: str
    description: str = ""
    source: str = Field(
        default="compose-stack", description="Source ref; 'compose-stack' = compose Postgres"
    )
    tables: list[SourceTable] = Field(default_factory=list)
    schedule_cron: str | None = None
