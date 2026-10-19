"""Analysis and collected usage must share account-scoped reference pricing."""

from pathlib import Path

import pytest

from trajectory.product.contracts import Price
from trajectory.product.domain import Domain


def configure(domain: Domain, owner: str = "owner", **fields: object) -> None:
    domain.price(
        owner,
        Price.model_validate(
            {
                "mutation_id": "glm-analysis-price-0001",
                "model": "glm-5.3",
                "input": 1.4,
                "cached": 0.26,
                "output": 4.4,
                "cache_write": 0,
                "basis": "current_reference",
                "effective_from": "2026-10-19T00:00:00Z",
                "verified_at": "2026-10-19T12:00:00+08:00",
                "source_url": "https://docs.z.ai/guides/overview/pricing",
                **fields,
            }
        ),
    )


def provenance(**usage: object) -> dict:
    return {
        "model": "glm-5.3",
        "created_at": "2026-10-19T05:00:00Z",
        "analysis_usage": [
            {
                "call_id": "call-1",
                "chunk": 1,
                "attempt": 1,
                "valid": True,
                "usage": {
                    "prompt_tokens": 1000,
                    "completion_tokens": 200,
                    "prompt_tokens_details": {"cached_tokens": 200},
                    "completion_tokens_details": {"reasoning_tokens": 120},
                    **usage,
                },
            }
        ],
    }


def test_reference_quote_excludes_cached_input_and_does_not_rebill_reasoning(
    tmp_path: Path,
) -> None:
    domain = Domain(tmp_path / "domain.db")
    configure(domain)
    original = provenance()
    quote = domain.analysis_cost("owner", original)
    assert quote["cost_status"] == "complete"
    assert quote["estimated_usd"] == pytest.approx((800 * 1.4 + 200 * 0.26 + 200 * 4.4) / 1e6)
    assert quote["actual_charge"] is None and quote["actual_charge_currency"] is None
    assert "cost" not in original
    assert quote["calls"][0]["price"]["source_url"] == "https://docs.z.ai/guides/overview/pricing"


def test_missing_cache_counter_is_not_zero_and_price_is_account_scoped(tmp_path: Path) -> None:
    domain = Domain(tmp_path / "domain.db")
    configure(domain)
    value = provenance(prompt_tokens_details={})
    result = domain.analysis_cost("owner", value)
    assert result["cost_status"] == "partial" and result["estimated_usd"] is None
    assert result["known_subtotal_usd"] == pytest.approx(200 * 4.4 / 1e6)
    assert result["unknown_reason_counts"] == {"missing_cached": 1}
    other = domain.analysis_cost("other-owner", value)
    assert other["cost_status"] == "unknown"
    assert other["unknown_reason_counts"] == {"missing_price": 1}


def test_failed_retry_usage_counted_once_by_stable_call_identity(tmp_path: Path) -> None:
    domain = Domain(tmp_path / "domain.db")
    configure(domain)
    value = provenance()
    value["analysis_usage"][0]["valid"] = False
    value["analysis_usage"].append(dict(value["analysis_usage"][0]))
    value["analysis_usage"].append(value["analysis_usage"][0] | {"call_id": "call-2", "attempt": 2})
    result = domain.analysis_cost("owner", value)
    assert len(result["calls"]) == 2
    assert result["estimated_usd"] == pytest.approx(2 * 0.002052)
    value["analysis_usage"][1]["usage"] = {"prompt_tokens": 20}
    assert domain.analysis_cost("owner", value)["estimated_usd"] is None


def test_no_usage_invalid_counts_and_missing_completion_stay_unknown(tmp_path: Path) -> None:
    domain = Domain(tmp_path / "domain.db")
    configure(domain)
    assert domain.analysis_cost("owner", {})["cost_status"] == "unknown"
    result = domain.analysis_cost("owner", provenance(prompt_tokens=True, completion_tokens=None))
    assert result["estimated_usd"] is None
    assert "missing_input" in result["unknown_reason_counts"]
    assert "missing_output" in result["unknown_reason_counts"]


def test_reference_price_update_revalues_without_mutating_analysis(tmp_path: Path) -> None:
    domain = Domain(tmp_path / "domain.db")
    configure(domain)
    value = provenance()
    before = domain.analysis_cost("owner", value)["estimated_usd"]
    configure(domain, input=2.8, mutation_id="glm-analysis-price-0002")
    after = domain.analysis_cost("owner", value)["estimated_usd"]
    assert after - before == pytest.approx(800 * 1.4 / 1e6)
    assert value == provenance()
