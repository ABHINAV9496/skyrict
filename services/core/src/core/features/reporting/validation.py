"""Read-only report SQL validation (RPT-DATA-001, M-RPT §Rules).

The report-definition seeds embed the dataset query as SQL text
(``erp_report_definitions.sql``) executed later by the reporting engine.
Before any seed row is persisted - in migration 0036 and at tenant
provisioning time - the SQL is validated by this module so a misconfigured
definition can never become a write path.

Validation is intentionally a CONSERVATIVE LEXICAL SCANNER, not a full SQL
parser: there is deliberately no sqlparse dependency (the core service does
not ship a SQL parser, and adding one just to validate server-owned seed SQL
would be over-engineering). The scanner:

  - strips comments, string literals, quoted identifiers and dollar-quoted
    strings so their contents are never treated as executable keywords;
  - requires the first keyword to be ``SELECT`` (no CTEs, no set operations
    that hide a write, no parenthesized prefixes);
  - rejects side-effect keywords anywhere outside strings/comments
    (``UPDATE``, ``DELETE``, ``INSERT``, ``MERGE``, ``DROP``, ``CREATE``,
    ``ALTER``, ``TRUNCATE``, ``GRANT``, ``REVOKE``, ``COPY``, ``EXECUTE``,
    ``SELECT ... INTO``, transaction control, session commands ...);
  - rejects multiple statements (any ``;`` outside a string/comment);
  - extracts ``:name`` bind parameters (skipping PostgreSQL ``::`` cast
    syntax) and rejects any bind that is not declared in the definition's
    parameter whitelist.

The function returns the set of binds it found, so callers (and the seed
catalog test) can assert that the declared whitelist exactly matches the
binds actually used.
"""

from __future__ import annotations

from collections.abc import Collection

# Upper-case keywords that make the statement not-read-only or that start a
# separate statement. Covers DML, DDL, session/utility commands, transaction
# control and ``SELECT ... INTO`` (which creates a table). ``WITH`` is NOT
# banned on purpose: a read-only CTE is legitimate, and any data-modifying CTE
# contains one of the DML keywords below, which IS banned.
_FORBIDDEN_KEYWORDS: frozenset[str] = frozenset(
    {
        # Data modification
        "DELETE",
        "EXECUTE",
        "MERGE",
        "REFRESH",
        "UPDATE",
        "INSERT",
        # DDL / privilege / maintenance
        "ALTER",
        "ANALYZE",
        "CHECKPOINT",
        "CLUSTER",
        "COMMENT",
        "COPY",
        "CREATE",
        "DEALLOCATE",
        "DECLARE",
        "DISCARD",
        "DROP",
        "GRANT",
        "IMPORT",
        "INTO",
        "LOCK",
        "MOVE",
        "PREPARE",
        "REASSIGN",
        "REINDEX",
        "RESET",
        "REVOKE",
        "SET",
        "SHOW",
        "TRUNCATE",
        "VACUUM",
        # Session/transaction control
        "ABORT",
        "BEGIN",
        "CALL",
        "CLOSE",
        "COMMIT",
        "DO",
        "FETCH",
        "LISTEN",
        "LOAD",
        "NOTIFY",
        "RELEASE",
        "ROLLBACK",
        "SAVEPOINT",
        "START",
        "UNLISTEN",
    }
)

_IDENT_START = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_")
_IDENT_CHARS = _IDENT_START | frozenset("0123456789")


class ReportDefinitionValidationError(ValueError):
    """Raised when report SQL violates the read-only contract."""


def _read_identifier(sql: str, start: int) -> tuple[str, int]:
    """Read a keyword/identifier starting at ``start``; return (word, end)."""
    end = start
    while end < len(sql) and sql[end] in _IDENT_CHARS:
        end += 1
    return sql[start:end], end


def validate_read_only_sql(
    sql: str,
    allowed_params: Collection[str] = (),
) -> set[str]:
    """Validate ``sql`` is a single read-only SELECT statement.

    Raises :class:`ReportDefinitionValidationError` on any violation and
    returns the set of ``:name`` bind parameters actually used.
    """
    allowed = frozenset(allowed_params)
    used_binds: set[str] = set()

    i = 0
    n = len(sql)
    first_keyword: str | None = None

    while i < n:
        char = sql[i]

        # --- comments -------------------------------------------------------
        if char == "-" and i + 1 < n and sql[i + 1] == "-":
            newline = sql.find("\n", i + 2)
            i = n if newline == -1 else newline + 1
            continue
        if char == "/" and i + 1 < n and sql[i + 1] == "*":
            close = sql.find("*/", i + 2)
            if close == -1:
                raise ReportDefinitionValidationError("unterminated block comment")
            i = close + 2
            continue

        # --- string literals ------------------------------------------------
        if char == "'":
            i = _skip_single_quoted(sql, i)
            continue
        if char == '"':
            i = _skip_double_quoted(sql, i)
            continue
        if char == "$" and (i + 1 >= n or sql[i + 1] not in "0123456789"):
            dollar_skip = _try_skip_dollar_quoted(sql, i)
            if dollar_skip is not None:
                i = dollar_skip
                continue

        # --- bind parameters (skip PostgreSQL :: casts) ----------------------
        if char == ":":
            if i + 1 < n and sql[i + 1] == ":":
                i += 2  # :: cast operator - not a bind
                continue
            if i + 1 < n and sql[i + 1] in _IDENT_START:
                name, i = _read_identifier(sql, i + 1)
                used_binds.add(name)
                continue
            i += 1
            continue

        # --- statement separators -------------------------------------------
        if char == ";":
            raise ReportDefinitionValidationError("multiple statements are not allowed (found ';')")

        # --- keywords --------------------------------------------------------
        if char in _IDENT_START:
            word, i = _read_identifier(sql, i)
            upper = word.upper()
            if upper in _FORBIDDEN_KEYWORDS:
                raise ReportDefinitionValidationError(
                    f"forbidden keyword {word!r} in read-only report SQL"
                )
            if first_keyword is None:
                first_keyword = upper
                if upper != "SELECT":
                    raise ReportDefinitionValidationError(
                        f"SQL must start with SELECT, got {word!r}"
                    )
            continue

        # positional parameter like $1 - accepted (ignored) rather than
        # treated as a quoted string; report SQL uses named binds only.
        if char == "$":
            i += 1
            continue

        i += 1

    if first_keyword is None:
        raise ReportDefinitionValidationError("empty SQL - SELECT statement required")

    undeclared = used_binds - allowed
    if undeclared:
        raise ReportDefinitionValidationError(
            "bind parameters used but not declared in the whitelist: "
            f"{', '.join(sorted(undeclared))}"
        )

    return used_binds


def _skip_single_quoted(sql: str, start: int) -> int:
    """Skip a ``'...'`` literal honouring ``''`` escapes. Returns next index."""
    i = start + 1
    n = len(sql)
    while i < n:
        if sql[i] == "'":
            if i + 1 < n and sql[i + 1] == "'":
                i += 2  # escaped quote
                continue
            return i + 1
        i += 1
    raise ReportDefinitionValidationError("unterminated string literal")


def _skip_double_quoted(sql: str, start: int) -> int:
    """Skip a ``\"...\"`` quoted identifier honouring ``\"\"`` escapes."""
    i = start + 1
    n = len(sql)
    while i < n:
        if sql[i] == '"':
            if i + 1 < n and sql[i + 1] == '"':
                i += 2
                continue
            return i + 1
        i += 1
    raise ReportDefinitionValidationError("unterminated quoted identifier")


def _try_skip_dollar_quoted(sql: str, start: int) -> int | None:
    """Return the index after a ``$tag$ ... $tag$`` literal, or None.

    Callers only invoke this for ``$`` not followed by a digit (a ``$1``
    positional parameter must not be treated as a dollar-quoted string).
    """
    close_tag = sql.find("$", start + 1)
    if close_tag == -1:
        return None
    tag = sql[start + 1 : close_tag]
    if not (tag == "" or (tag[0] in _IDENT_START and all(c in _IDENT_CHARS for c in tag))):
        return None
    terminator = sql.find("$" + tag + "$", close_tag + 1)
    if terminator == -1:
        raise ReportDefinitionValidationError("unterminated dollar-quoted string")
    return terminator + len(tag) + 2
