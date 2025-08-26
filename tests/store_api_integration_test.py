import json
import pytest
from api import create_app

# RUN USING python -m pytest -v

@pytest.fixture
def client(tmp_path):
    db = tmp_path / "api.sqlite3"
    app = create_app(str(db))
    app.config.update(TESTING=True)
    return app.test_client()

def test_session_lifecycle_and_kv_visibility(client):
    # Create a session
    r = client.post("/session")
    assert r.status_code == 200
    sid = r.get_json()["session_id"]
    hdr = {"X-Session-ID": sid}

    # Begin tx
    r = client.post(f"/session/{sid}/begin")
    assert r.status_code == 200
    assert r.get_json()["depth"] == 1

    # Set a key (staged)
    r = client.put("/store/user42", data=json.dumps({"value": {"name": "Ava"}}),
                   headers={**hdr, "Content-Type": "application/json"})
    assert r.status_code == 200

    # Read inside session (visible)
    r = client.get("/store/user42", headers=hdr)
    assert r.status_code == 200
    body = r.get_json()
    assert body["found"] is True and body["value"]["name"] == "Ava"

    # Read without session (not visible before commit)
    r = client.get("/store/user42")
    assert r.status_code == 404

    # Commit
    r = client.post(f"/session/{sid}/commit")
    assert r.status_code == 200
    assert r.get_json()["depth"] == 0

    # Now visible to everyone
    r = client.get("/store/user42")
    assert r.status_code == 200
    assert r.get_json()["value"]["name"] == "Ava"

def test_autocommit_without_session(client):
    # Put directly (autocommit)
    r = client.put("/store/k", data=json.dumps({"value": 123}),
                   headers={"Content-Type": "application/json"})
    assert r.status_code == 200

    # Get should succeed without session
    r = client.get("/store/k")
    assert r.status_code == 200
    assert r.get_json()["value"] == 123

def test_delete_and_not_found_shape(client):
    # Create session and begin
    sid = client.post("/session").get_json()["session_id"]
    hdr = {"X-Session-ID": sid}
    client.post(f"/session/{sid}/begin")

    # Put then delete inside tx
    client.put("/store/todelete", data=json.dumps({"value": "x"}),
               headers={**hdr, "Content-Type": "application/json"})
    client.delete("/store/todelete", headers=hdr)

    # Not visible in-session after delete
    r = client.get("/store/todelete", headers=hdr)
    assert r.status_code == 404
    body = r.get_json()
    assert body == {"key": "todelete", "value": None, "found": False}

    # Commit makes delete permanent
    client.post(f"/session/{sid}/commit")
    r = client.get("/store/todelete")
    assert r.status_code == 404

def test_bad_requests(client):
    # Missing value in PUT
    r = client.put("/store/oops", data="{}", headers={"Content-Type": "application/json"})
    assert r.status_code in (400, 415)  # 400 if handler coerces JSON; 415 if not

    # Unknown session id
    r = client.post("/session/does-not-exist/begin")
    assert r.status_code == 404

def test_nested_commit_rollback(client):
    sid = client.post("/session").get_json()["session_id"]
    hdr = {"X-Session-ID": sid, "Content-Type": "application/json"}

    client.post(f"/session/{sid}/begin")      # depth 1
    client.put("/store/x", data=json.dumps({"value": 10}), headers=hdr)
    client.post(f"/session/{sid}/begin")      # depth 2
    client.put("/store/x", data=json.dumps({"value": 20}), headers=hdr)

    # Read shows 20 inside session
    assert client.get("/store/x", headers={"X-Session-ID": sid}).get_json()["value"] == 20

    # Commit inner (merge to parent, still uncommitted)
    client.post(f"/session/{sid}/commit")     # depth 1
    assert client.get("/store/x", headers={"X-Session-ID": sid}).get_json()["value"] == 20
    # DB still not updated
    assert client.get("/store/x").status_code == 404

    # Rollback outer (discard changes)
    client.post(f"/session/{sid}/rollback")   # depth 0
    assert client.get("/store/x").status_code == 404
