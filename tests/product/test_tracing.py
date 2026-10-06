import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from trajectory.product.server import create_app


def test_public_rejection_scope_denial_and_read_have_private_bounded_traces(
    tmp_path: Path, monkeypatch
):
    from batcave_http import auth, authority

    owner = str(uuid.uuid4())
    monkeypatch.setenv("BATCAVE_AUTHORITY_CONFIG", "configured-by-test")
    monkeypatch.setattr(
        auth,
        "registered_key",
        lambda token, service, scope: (
            {"account_id": owner, "key_id": "known-key", "scopes": ["read"]}
            if token == "Bearer valid-private-key"
            else None
        ),
    )
    monkeypatch.setattr(authority, "account_allowed", lambda *args, **kwargs: True)
    app = create_app(tmp_path / "domain.db")
    client = TestClient(app)
    public = client.get(
        "/trajectory/help", headers={"X-Forwarded-User": owner, "X-BatCave-Request-ID": "spoofed"}
    )
    assert public.status_code == 401
    anonymous = client.get("/trajectory/health?private-secret=query")
    assert anonymous.status_code == 200
    read = client.get(
        "/trajectory/api/overview", headers={"Authorization": "Bearer valid-private-key"}
    )
    assert read.headers["x-batcave-account"] == owner
    denied = client.get(
        "/trajectory/api/platform", headers={"Authorization": "Bearer valid-private-key"}
    )
    assert denied.status_code == 403 and denied.headers["x-batcave-account"] == owner
    invalid = client.get(
        "/trajectory/api/overview",
        headers={"Authorization": "Bearer invalid-private-key", "X-Forwarded-User": owner},
    )
    assert invalid.status_code == 403 and "x-batcave-account" not in invalid.headers
    traces = app.state.domain.traces()["items"]
    assert len({item["request_id"] for item in traces}) == 5
    assert (
        traces[0]["account_id"] is None
        and traces[0]["authentication_outcome"] == "credential_unrecognized"
    )
    assert (
        traces[1]["authentication_outcome"] == "scope_denied" and traces[1]["key_id"] == "known-key"
    )
    assert traces[-2]["source"] == "public_health"
    assert "private-key" not in str(traces) and "private-secret" not in str(traces)
