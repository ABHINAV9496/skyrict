"""Cross-module intelligence narrator (SKY-63).

A daily executive digest that joins Finance x Sales x Inventory x CRM signals
and renders them as a short plain-language narrative. Slice layout:

- ``gateway``  read-only HTTP port over the core monolith's four modules
- ``extract``  collapse module signals into a compact gold-signal payload
- ``narrate``  deterministic LLM call that turns signals into a digest
- ``service``  orchestration: cache, refresh gate, abstention, audit
- ``scheduler`` APScheduler cron that produces the daily digest

The narrator READS modules over HTTP and never mutates them; the LLM is
reached only through the shared ``LlmRouter``.
"""
