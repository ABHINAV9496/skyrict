"""Read-only report SQL validator unit tests (RPT-DATA-001 acceptance).

Gherkin coverage for the read-only contract:

  Feature: Report definition SQL stays read-only
    Scenario: A non-SELECT seed is rejected before any INSERT is attempted
    Scenario: A write keyword anywhere is rejected
    Scenario: Multiple statements are rejected
    Scenario: Undeclared binds are rejected; declared binds pass
    Scenario: Comments, literals and casts never falsify the checks
"""

from __future__ import annotations

import pytest

from core.features.reporting.validation import (
    ReportDefinitionValidationError,
    validate_read_only_sql,
)


class TestBasicReadOnly:
    def test_plain_select_passes_and_reports_binds(self) -> None:
        sql = "SELECT id, name FROM erp_customers WHERE tenant_id = :tenant_id"
        binds = validate_read_only_sql(sql, ("tenant_id",))
        assert binds == {"tenant_id"}

    def test_select_with_subquery_passes(self) -> None:
        sql = (
            "SELECT * FROM (SELECT id FROM erp_invoices "
            "WHERE tenant_id = :tenant_id) AS inner_query"
        )
        binds = validate_read_only_sql(sql, ("tenant_id",))
        assert binds == {"tenant_id"}

    def test_leading_comments_and_whitespace_ok(self) -> None:
        sql = "-- report header\n/* block\ncomment */\nSELECT 1"
        assert validate_read_only_sql(sql) == set()

    def test_empty_sql_rejected(self) -> None:
        with pytest.raises(ReportDefinitionValidationError, match="empty SQL"):
            validate_read_only_sql("   \n  ")

    def test_non_select_first_keyword_rejected(self) -> None:
        with pytest.raises(ReportDefinitionValidationError, match="must start with SELECT"):
            validate_read_only_sql("WITH x AS (SELECT 1) SELECT * FROM x")

    def test_cte_rejected(self) -> None:
        with pytest.raises(ReportDefinitionValidationError, match="must start with SELECT"):
            validate_read_only_sql("WITH x AS (SELECT 1) SELECT * FROM x")

    def test_data_modifying_cte_rejected(self) -> None:
        with pytest.raises(ReportDefinitionValidationError, match="must start with SELECT"):
            validate_read_only_sql("WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x")


class TestForbiddenKeywords:
    @pytest.mark.parametrize(
        "sql",
        [
            "UPDATE erp_customers SET name = 'x'",
            "DELETE FROM erp_customers",
            "INSERT INTO erp_customers (id) VALUES (1)",
            "MERGE INTO erp_customers c USING s ON ...",
            "DROP TABLE erp_customers",
            "CREATE TABLE erp_customers (id int)",
            "ALTER TABLE erp_customers ADD COLUMN x int",
            "TRUNCATE erp_customers",
            "GRANT SELECT ON erp_customers TO bob",
            "REVOKE SELECT ON erp_customers FROM bob",
            "COPY erp_customers TO STDOUT",
            "EXECUTE some_proc",
            "SELECT 1 INTO tmp_table",
            "BEGIN; SELECT 1",
        ],
    )
    def test_write_keywords_rejected(self, sql: str) -> None:
        with pytest.raises(ReportDefinitionValidationError, match="forbidden keyword"):
            validate_read_only_sql(sql)


class TestStatementSplitting:
    def test_semicolon_separated_rejected(self) -> None:
        with pytest.raises(ReportDefinitionValidationError, match="multiple statements"):
            validate_read_only_sql("SELECT 1; SELECT 2")

    def test_trailing_semicolon_rejected(self) -> None:
        with pytest.raises(ReportDefinitionValidationError, match="multiple statements"):
            validate_read_only_sql("SELECT 1;")


class TestBindWhitelist:
    def test_bind_outside_whitelist_rejected(self) -> None:
        sql = "SELECT * FROM t WHERE tenant_id = :tenant_id AND x = :sneaky"
        with pytest.raises(ReportDefinitionValidationError, match="sneaky"):
            validate_read_only_sql(sql, ("tenant_id",))

    def test_extra_declared_params_allowed(self) -> None:
        sql = "SELECT * FROM t WHERE tenant_id = :tenant_id"
        binds = validate_read_only_sql(sql, ("tenant_id", "from_date", "to_date"))
        assert binds == {"tenant_id"}


class TestLexicalSensitivity:
    def test_keyword_inside_string_ignored(self) -> None:
        sql = "SELECT 'UPDATE customers SET total = 9' AS note"
        assert validate_read_only_sql(sql) == set()

    def test_keyword_inside_comment_ignored(self) -> None:
        sql = "-- UPDATE is fine in a comment\nSELECT 1"
        assert validate_read_only_sql(sql) == set()

    def test_cast_operator_not_treated_as_bind(self) -> None:
        sql = "SELECT total::numeric FROM t WHERE tenant_id = :tenant_id"
        binds = validate_read_only_sql(sql, ("tenant_id",))
        assert binds == {"tenant_id"}

    def test_lowercase_write_keyword_still_rejected(self) -> None:
        with pytest.raises(ReportDefinitionValidationError, match="forbidden keyword"):
            validate_read_only_sql("update erp_customers set name = 'x'")

    def test_escaped_quotes_in_string_ignored(self) -> None:
        sql = "SELECT 'it''s fine' AS note, :tenant_id AS tid"
        binds = validate_read_only_sql(sql, ("tenant_id",))
        assert binds == {"tenant_id"}

    def test_dollar_quoted_string_ignored(self) -> None:
        sql = "SELECT $tag$UPDATE something$tag$ AS note"
        assert validate_read_only_sql(sql) == set()

    def test_positional_param_not_treated_as_string(self) -> None:
        # $1 is a positional parameter - accepted but not mistaken for a
        # dollar-quoted string or a named bind.
        sql = "SELECT $1 AS value"
        assert validate_read_only_sql(sql) == set()


class TestMalformedLiterals:
    def test_unterminated_string_rejected(self) -> None:
        with pytest.raises(ReportDefinitionValidationError, match="unterminated string"):
            validate_read_only_sql("SELECT 'oops")

    def test_unterminated_block_comment_rejected(self) -> None:
        with pytest.raises(ReportDefinitionValidationError, match="unterminated block comment"):
            validate_read_only_sql("SELECT 1 /* never closes")
