"""Content-addressed research assets retain authentication during revalidation."""

import hashlib
import re
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from trajectory.product.server import Principal, create_app


@pytest.mark.parametrize("name", ["research.js", "research.css"])
def test_asset_etag_is_content_bound_and_revocation_precedes_304(tmp_path: Path, name: str):
    active = {"reader": True}

    def authorize(request, scope):
        if request.headers.get("Authorization") == "reader" and active["reader"]:
            assert scope == "read"
            return Principal("test-reader", scopes=("read",))
        raise HTTPException(403, "Denied")

    client = TestClient(create_app(tmp_path / "assets.db", authorize))
    path = "/trajectory/" + name
    first = client.get(path, headers={"Authorization": "reader"})
    assert first.status_code == 200
    etag = '"' + hashlib.sha256(first.content).hexdigest() + '"'
    assert first.headers["ETag"] == etag
    assert first.headers["Cache-Control"] == "private, no-cache"
    assert first.headers["Vary"] == "Authorization"
    for supplied in (etag, '"other", W/' + etag):
        cached = client.get(path, headers={"Authorization": "reader", "If-None-Match": supplied})
        assert cached.status_code == 304
        assert not cached.content
        assert cached.headers["ETag"] == etag
    changed = client.get(path, headers={"Authorization": "reader", "If-None-Match": '"old"'})
    assert changed.status_code == 200 and changed.content == first.content
    active["reader"] = False
    assert (
        client.get(path, headers={"Authorization": "reader", "If-None-Match": etag}).status_code
        == 403
    )


def test_dashboard_keys_both_assets_from_their_actual_content(tmp_path: Path):
    def authorize(request, scope):
        return Principal("test-reader", scopes=("read",))

    client = TestClient(create_app(tmp_path / "dashboard.db", authorize))
    html = client.get("/trajectory/").text
    js = client.get("/trajectory/research.js").content
    css = client.get("/trajectory/research.css").content
    revision = hashlib.sha256(js + b"\0" + css).hexdigest()[:16]
    assert "__TRAJECTORY_RESEARCH_REVISION__" not in html
    assert re.findall(r"/trajectory/research\.(?:js|css)\?rev=([a-f0-9]+)", html) == [
        revision,
        revision,
    ]
