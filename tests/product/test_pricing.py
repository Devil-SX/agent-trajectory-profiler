from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from trajectory.product.contracts import Batch, Price
from trajectory.product.domain import Domain
from trajectory.product.server import Principal, create_app


def fixture_domain(tmp_path: Path, records: list[dict]) -> Domain:
    domain = Domain(tmp_path / "pricing.db")
    domain.register("owner", "machine", "fixture")
    domain.ingest(
        "machine",
        Batch.model_validate(
            {
                "mutation_id": "pricing-batch-000001",
                "collector": "fixture",
                "source": "pricing-source-000001",
                "revision": 1,
                "source_bytes": 100,
                "read_bytes": 100,
                "parser_version": "fixture/1",
                "records": [
                    {
                        "id": f"pricing-usage-{i:016}",
                        "session": "session",
                        "task": "task",
                        "ecosystem": "codex",
                        "timestamp": "2026-10-01T00:00:00Z",
                        "kind": "usage",
                        "model": "example",
                        "source_line": i + 1,
                        "input": 100,
                        "output": 20,
                        "cached": 50,
                        "input_includes_cache": True,
                    }
                    | record
                    for i, record in enumerate(records)
                ],
            }
        ),
    )
    return domain


def price(**fields) -> Price:
    values = {
        "mutation_id": "pricing-price-000001",
        "model": "example",
        "input": 2,
        "output": 10,
        "cached": 0.1,
        "cache_write": 2.5,
        "effective_from": "2026-10-12T00:00:00Z",
        "source_url": "https://example.com/pricing",
        "basis": "current_reference",
        "verified_at": "2026-10-12T00:00:00Z",
    }
    values.update(fields)
    return Price.model_validate(values)


def test_current_reference_partial_cost_preserves_unknown_cache_write(tmp_path: Path) -> None:
    domain = fixture_domain(tmp_path, [{}])
    domain.price("owner", price())
    result = domain.overview("owner")
    row = result["projects"][0]
    assert row["estimated_usd"] is None
    assert row["known_subtotal_usd"] == pytest.approx(0.000205)
    assert row["unpriced_calls"] == 1 and row["priced_calls"] == 0
    assert row["unknown_reason_counts"] == {"missing_cache_write": 1}
    assert row["cost_status"] == "partial"
    assert result["pricing"]["prices"][0]["basis"] == "current_reference"
    assert isinstance(result["pricing"]["reference_assumptions"], list)
    assert any("historical bills" in item for item in result["pricing"]["reference_assumptions"])


def test_no_cache_write_charge_can_price_missing_counter(tmp_path: Path) -> None:
    domain = fixture_domain(tmp_path, [{}])
    domain.price("owner", price(cache_write=0))
    row = domain.overview("owner")["projects"][0]
    assert row["priced_calls"] == 1 and row["unpriced_calls"] == 0
    assert row["estimated_usd"] == pytest.approx(0.000305)
    assert row["cost_status"] == "complete"


def test_historical_price_does_not_apply_before_effective_date(tmp_path: Path) -> None:
    domain = fixture_domain(tmp_path, [{}])
    domain.price("owner", price(basis="effective_historical", verified_at=None))
    row = domain.overview("owner")["projects"][0]
    assert row["estimated_usd"] is None
    assert row["cost_status"] == "unknown"
    assert row["unknown_reason_counts"] == {"missing_price": 1}
    domain.price(
        "owner",
        price(
            mutation_id="pricing-price-000002",
            basis="effective_historical",
            verified_at=None,
            effective_from="2026-09-01T00:00:00Z",
            cache_write=0,
        ),
    )
    assert domain.overview("owner")["projects"][0]["priced_calls"] == 1


@pytest.mark.parametrize("scope, expected", [("request", 0.000915), ("session", 0.00122)])
def test_context_boundary_and_observed_session_scope(
    tmp_path: Path, scope: str, expected: float
) -> None:
    domain = fixture_domain(tmp_path, [{}, {"input": 101}])
    domain.price(
        "owner",
        price(
            cache_write=0,
            context_scope=scope,
            long_context_threshold=100,
            long_context={"input": 4, "output": 20, "cached": 0.2, "cache_write": 0},
        ),
    )
    row = domain.overview("owner")["projects"][0]
    assert row["estimated_usd"] == pytest.approx(expected + 0.000004)


def test_price_reference_schema_is_discoverable_and_validated(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="verified_at"):
        price(verified_at=None)
    with pytest.raises(ValidationError, match="together"):
        price(long_context_threshold=100)
    with pytest.raises(ValidationError, match="Timezone"):
        price(verified_at="2026-10-12T00:00:00")
    app = create_app(
        tmp_path / "api.db", lambda request, scope: Principal("owner", scopes=("read", "configure"))
    )
    client = TestClient(app)
    help_response = client.get("/trajectory/help", headers={"authorization": "Bearer fixture"})
    assert help_response.status_code == 200
    assert (
        "current_reference" in help_response.text and "long_context_threshold" in help_response.text
    )
    response = client.post(
        "/trajectory/api/prices", json=price(cache_write=0).model_dump(mode="json")
    )
    assert response.status_code == 200 and response.json()["durable"]


@pytest.mark.parametrize(
    "included, expected, reason",
    [
        (True, 0.00032, None),
        (False, 0.00033, None),
        (None, None, "input_cache_write_semantics"),
    ],
)
def test_cache_write_input_semantics_prevent_double_charging(
    tmp_path: Path,
    included: bool | None,
    expected: float | None,
    reason: str | None,
) -> None:
    domain = fixture_domain(tmp_path, [{"cache_write": 5, "input_includes_cache_write": included}])
    domain.price("owner", price())
    row = domain.overview("owner")["projects"][0]
    if expected is None:
        assert row["estimated_usd"] is None
        assert row["unknown_reason_counts"] == {reason: 1}
        assert row["known_subtotal_usd"] == pytest.approx(0.0002175)
    else:
        assert row["estimated_usd"] == pytest.approx(expected - 0.0000125)


def test_invalid_cached_totals_are_reported_without_zero_clamping(tmp_path: Path) -> None:
    domain = fixture_domain(
        tmp_path, [{"input": 54, "cache_write": 5, "input_includes_cache_write": True}]
    )
    domain.price("owner", price())
    row = domain.overview("owner")["projects"][0]
    assert row["estimated_usd"] is None
    assert row["unknown_reason_counts"] == {"invalid_cache_counts": 1}
    assert row["known_subtotal_usd"] == pytest.approx(0.0002175)


def test_context_length_includes_independent_cached_tokens(tmp_path: Path) -> None:
    domain = fixture_domain(
        tmp_path,
        [
            {
                "input": 70,
                "cached": 50,
                "input_includes_cache": False,
                "input_includes_cache_write": False,
                "cache_write": 0,
            }
        ],
    )
    domain.price(
        "owner",
        price(
            cache_write=0,
            long_context_threshold=100,
            long_context={"input": 4, "output": 20, "cached": 0.2, "cache_write": 0},
        ),
    )
    row = domain.overview("owner")["projects"][0]
    assert row["estimated_usd"] == pytest.approx(0.00069)
