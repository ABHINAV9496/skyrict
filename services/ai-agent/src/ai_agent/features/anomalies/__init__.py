"""Stock anomaly detection + review workflow (feature 3, spec §4).

Slice layout: ``rules`` (deterministic detection over recent movements),
``service`` (scan + review with audit), backed by the ai_anomalies
repository. Detection is pure computation - NO LLM call is involved.

Rule coverage (spec §4.2): v1 implements sudden_stock_drop,
unusual_adjustment_size, duplicate_movement_ref, and
off_hours_movement. The remaining spec patterns (transfer_without_receipt,
stock_level_mismatch, reorder_alert_ignored, negative_adjustment_spike)
require full ledger access or alert history that core does not expose yet;
the rules module documents each deferral.
"""
