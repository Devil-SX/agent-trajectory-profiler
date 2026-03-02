"""Rule-based tool error taxonomy for trajectory analytics."""

from __future__ import annotations

import re
from dataclasses import dataclass

ERROR_TAXONOMY_VERSION = "1.0.0"
UNCATEGORIZED_ERROR = "uncategorized"


@dataclass(frozen=True)
class ErrorTaxonomyRule:
    """Single taxonomy rule entry."""

    rule_id: str
    category: str
    label: str
    pattern: str

    def regex(self) -> re.Pattern[str]:
        return re.compile(self.pattern, re.IGNORECASE)


@dataclass(frozen=True)
class ErrorClassification:
    """Taxonomy classification result."""

    category: str
    label: str
    rule_id: str | None = None


ERROR_TAXONOMY_RULES: tuple[ErrorTaxonomyRule, ...] = (
    ErrorTaxonomyRule(
        rule_id="permission_denied",
        category="permission",
        label="Permission Denied",
        pattern=r"permission denied|operation not permitted|eacces|eperm",
    ),
    ErrorTaxonomyRule(
        rule_id="command_not_found",
        category="command",
        label="Command Not Found",
        pattern=r"command not found|is not recognized as an internal or external command",
    ),
    ErrorTaxonomyRule(
        rule_id="file_not_found",
        category="file_not_found",
        label="File Not Found",
        pattern=r"no such file|not found|enoent|cannot stat|does not exist",
    ),
    ErrorTaxonomyRule(
        rule_id="timeout",
        category="timeout",
        label="Timeout",
        pattern=r"timed out|timeout|deadline exceeded",
    ),
    ErrorTaxonomyRule(
        rule_id="rate_limited",
        category="rate_limit",
        label="Rate Limited",
        pattern=r"rate limit|too many requests|429",
    ),
    ErrorTaxonomyRule(
        rule_id="network",
        category="network",
        label="Network Error",
        pattern=r"connection refused|connection reset|network|enotfound|dns",
    ),
    ErrorTaxonomyRule(
        rule_id="auth",
        category="authentication",
        label="Authentication Error",
        pattern=r"unauthorized|forbidden|invalid api key|authentication failed",
    ),
    ErrorTaxonomyRule(
        rule_id="patch_apply_failed",
        category="patch",
        label="Patch Apply Failed",
        pattern=r"patch failed|hunk failed|apply_patch verification failed",
    ),
    ErrorTaxonomyRule(
        rule_id="parse_error",
        category="parsing",
        label="Parsing Error",
        pattern=r"jsondecodeerror|parse error|invalid json|yaml",
    ),
    ErrorTaxonomyRule(
        rule_id="test_failure",
        category="test_failure",
        label="Test Failure",
        pattern=r"assertionerror|\\bfailed\\b|traceback",
    ),
)

_COMPILED_RULES = tuple((rule, rule.regex()) for rule in ERROR_TAXONOMY_RULES)


def classify_tool_error(detail: str) -> ErrorClassification:
    """Classify raw tool error text into a taxonomy category."""
    normalized = detail.strip()
    if not normalized:
        return ErrorClassification(
            category=UNCATEGORIZED_ERROR,
            label="Uncategorized",
            rule_id=None,
        )

    for rule, regex in _COMPILED_RULES:
        if regex.search(normalized):
            return ErrorClassification(
                category=rule.category,
                label=rule.label,
                rule_id=rule.rule_id,
            )

    return ErrorClassification(
        category=UNCATEGORIZED_ERROR,
        label="Uncategorized",
        rule_id=None,
    )
