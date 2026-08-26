"""Natural-language inventory queries (feature 1, spec §2).

Slice layout: ``intent`` (validated LLM output schema), ``matcher`` (name ->
catalog row resolution), ``gateway`` (read-only core HTTP port), ``engine``
(parse-resolve-execute-format pipeline), ``service`` (limits + logs + audit).
"""
