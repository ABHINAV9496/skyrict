"""Smart restock suggestions (feature 2, spec §3).

Slice layout: ``calculator`` (pure v1 formula), ``service`` (scan +
approval workflow with limits/logs/audit), backed by the ai_suggestions
repository. Suggestion creation is deterministic computation over core
data - NO LLM call is involved anywhere in this feature.
"""
