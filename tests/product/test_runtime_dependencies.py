"""The installed entrypoint must reject obsolete shared clients before serving."""

import pytest

from trajectory.product.runtime_dependencies import verify_http_runtime


def test_current_shared_contract_does_not_call_identity(monkeypatch):
    import batcave_http.auth as auth

    def never_call(account_id, service, scope, *, key_id=None, machine_client_id=None):
        raise AssertionError("Import probe called identity")

    monkeypatch.setattr(auth, "authorize_stored_account", never_call)
    value = verify_http_runtime()
    assert value["stored_account_authorization"]
    assert not value["network_requests"] and not value["database_opened"]


@pytest.mark.parametrize("replacement", [None, lambda account_id: None])
def test_obsolete_shared_contract_is_not_ready(monkeypatch, replacement):
    import batcave_http.auth as auth

    monkeypatch.setattr(auth, "authorize_stored_account", replacement)
    with pytest.raises(RuntimeError, match="stored-account authorization"):
        verify_http_runtime()


def test_entrypoint_probe_does_not_open_database(tmp_path):
    import json
    import os
    import subprocess
    import sys

    database = tmp_path / "must-not-exist.sqlite"
    result = subprocess.run(
        [sys.executable, "-m", "trajectory.product.server", "--check-runtime"],
        env={**os.environ, "TRAJECTORY_DB": str(database)},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["database_opened"] is False
    assert not database.exists()


def test_entrypoint_rejects_old_shared_runtime_before_database(tmp_path):
    import os
    import subprocess
    import sys

    legacy = tmp_path / "legacy" / "batcave_http"
    legacy.mkdir(parents=True)
    (legacy / "__init__.py").write_text("")
    (legacy / "auth.py").write_text("def registered_key(*args): return None\n")
    database = tmp_path / "must-not-exist.sqlite"
    result = subprocess.run(
        [sys.executable, "-m", "trajectory.product.server", "--check-runtime"],
        env={**os.environ, "PYTHONPATH": str(legacy.parent), "TRAJECTORY_DB": str(database)},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert "stored-account authorization" in result.stderr
    assert not database.exists()
