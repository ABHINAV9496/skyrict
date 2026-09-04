"""RAG feature package (SKY-58) - retrieval, ingestion, and evaluation.

Layering follows the repo import-linter contracts: everything under
``ai_agent.features`` must NOT import ``ai_agent.models`` or ``ai_agent.db``;
repositories are injected from the composition root.
"""
