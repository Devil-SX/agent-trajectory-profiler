"""Regression tests for rule-based tool error taxonomy."""

from __future__ import annotations

import json
from pathlib import Path

from claude_vis.parsers.error_taxonomy import (
    ERROR_TAXONOMY_VERSION,
    UNCATEGORIZED_ERROR,
    classify_tool_error,
)


def _load_examples() -> list[dict[str, str | None]]:
    fixture_path = Path(__file__).parent / "fixtures" / "error_taxonomy_examples.json"
    with fixture_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def test_error_taxonomy_examples_precision() -> None:
    """Validate taxonomy precision against curated examples."""
    examples = _load_examples()
    total = len(examples)
    matched = 0
    misses: list[str] = []

    for sample in examples:
        result = classify_tool_error(str(sample["detail"]))
        expected_category = sample["expected_category"]
        expected_rule_id = sample["expected_rule_id"]
        if result.category == expected_category and result.rule_id == expected_rule_id:
            matched += 1
        else:
            misses.append(
                f'{sample["id"]}: expected({expected_category}, {expected_rule_id}) '
                f"got({result.category}, {result.rule_id})"
            )

    precision = matched / total if total else 0.0
    note = (
        f"taxonomy precision={precision:.3f} ({matched}/{total}); "
        f"misses={'; '.join(misses) if misses else 'none'}"
    )
    # Precision note: this fixture set covers the currently supported rule families
    # and baseline fallback behavior; update examples whenever taxonomy rules evolve.
    assert precision >= 0.95, note


def test_error_taxonomy_version_semver_shape() -> None:
    """Version marker should be explicitly versioned for analytics compatibility."""
    segments = ERROR_TAXONOMY_VERSION.split(".")
    assert len(segments) == 3
    assert all(segment.isdigit() for segment in segments)


def test_error_taxonomy_uncategorized_fallback() -> None:
    """Unknown tool errors should be bucketed to uncategorized."""
    result = classify_tool_error("nonstandard failure mode with bespoke output")
    assert result.category == UNCATEGORIZED_ERROR
    assert result.rule_id is None
