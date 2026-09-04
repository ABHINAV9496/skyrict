"""Restock Advisor - the SKY-59 HITL demo agent (feature slice).

The agent module contract lives in ``graph.py``: ``build_graph(deps)``
returns an uncompiled ``StateGraph`` the runtime compiles with the
tenant-scoped checkpointer. The ``restock_advisor`` registry seed (migration
0008) wires ``ai_agent.features.restock_agent.graph`` with the tool allowlist
``["query_stock", "draft_suggestion", "apply_suggestion"]``.
"""
