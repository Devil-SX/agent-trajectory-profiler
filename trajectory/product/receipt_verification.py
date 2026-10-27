"""Read-only Jindu verification for explicit operator decisions, never upstream dispatch."""

import json
import urllib.request
import uuid
from datetime import UTC, datetime
from typing import Any

from trajectory.product.semantic_model import NoRedirect, _configuration


def verify_lost_receipt(call_id: str, receipt_id: str, route: str, model: str) -> dict[str, Any]:
    config = _configuration()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)

    def get(path: str) -> dict[str, Any]:
        request = urllib.request.Request(
            config["base_url"].rstrip("/") + path,
            headers={"Authorization": "Bearer " + config["api_key"], "Cache-Control": "no-store"},
        )
        with opener.open(request, timeout=10) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("Jindu receipt metadata exceeds limit")
        value: dict[str, Any] = json.loads(raw)
        return value

    help_value = get("/help")
    caller = help_value.get("caller", {})
    if not (
        caller.get("account_id")
        and caller.get("machine_client_id")
        and caller.get("key_id")
        and caller.get("source_service") == "trajectory"
        and "jindu.read" in caller.get("scopes", [])
    ):
        raise ValueError("Trajectory native Jindu read identity required")
    # Looking in the recent-call list loses older receipts once newer calls arrive.
    # The account-bound detail endpoint verifies ownership for this exact UUID.
    if str(uuid.UUID(receipt_id)) != receipt_id.lower():
        raise ValueError("Invalid Jindu receipt identity")
    receipt = get("/calls/" + receipt_id)
    if not (
        receipt.get("id") == receipt_id
        and receipt.get("account_id") == caller["account_id"]
        and receipt.get("source_service") == "trajectory"
        and receipt.get("route") == route
        and receipt.get("model") == model
        and receipt.get("state") == "uncertain"
        and receipt.get("finished") is not None
    ):
        raise ValueError("Jindu receipt identity or terminal state does not match")
    return {"caller": caller, "receipt": receipt, "verified_at": datetime.now(UTC).isoformat()}
