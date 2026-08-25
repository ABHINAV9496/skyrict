"""Foundations layer: config, constants, exceptions, logging, security,
tenant context/resolution, Redis client, LLM providers.

Never imports from ``ai_agent.features`` or ``ai_agent.api`` (enforced by
import-linter).
"""
