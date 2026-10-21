"""Fail before service startup when the deployed shared authorization API is stale."""

import importlib
import inspect
from typing import Any


def verify_http_runtime() -> dict[str, Any]:
    auth = importlib.import_module("batcave_http.auth")
    authorize = getattr(auth, "authorize_stored_account", None)
    required = {"account_id", "service", "scope", "key_id", "machine_client_id"}
    if not callable(authorize) or not required <= set(inspect.signature(authorize).parameters):
        raise RuntimeError(
            "Shared HTTP runtime lacks stored-account authorization; "
            "use the canonical shared runtime configuration"
        )
    if not callable(getattr(auth, "registered_key", None)):
        raise RuntimeError("Shared HTTP runtime lacks registered-key authorization")
    return {
        "status": "ready",
        "auth_module": auth.__file__,
        "stored_account_authorization": True,
        "registered_key_authorization": True,
        "network_requests": 0,
        "database_opened": False,
    }
