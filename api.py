import uuid, os
from flask import Flask, request, jsonify, abort
from arcade_store.store import Store

"""
arcade_store.api

Flask application exposing the transactional key-value store as a REST API.

Endpoints:
- Session management: /session, /session/<sid>/{begin,commit,rollback}
- Key/value operations: /store/<key> [PUT, GET, DELETE]
"""

def create_app(db_path=None):
    app = Flask(__name__)

    # Shared store instance (SQLite-backed).
    store = Store(db_path or os.getenv("STORE_DB_PATH", "kv.sqlite3"))

    # In-memory session registry: sid -> KvSession
    _sessions = {}

    def _get_session(req):
        """
        Resolve the KvSession for the current request.

        Priority:
        - If X-Session-ID header or ?session=<id> is provided → use that session.
        - If no session id → return a fresh autocommit session.
        Raises 404 if the session id is unknown.
        """
        sid = req.headers.get("X-Session-ID") or req.args.get("session")
        if not sid:
            # Use a temporary autocommit session (no transaction stack).
            return store.new_session()
        if sid not in _sessions:
            abort(404, description="Unknown session id")
        return _sessions[sid]

    @app.post("/session")
    def create_session():
        """Create and register a new session."""
        s = store.new_session()
        sid = str(uuid.uuid4())
        _sessions[sid] = s
        return jsonify({"session_id": sid})

    @app.post("/session/<sid>/begin")
    def begin_tx(sid):
        """Start a new nested transaction layer for the session."""
        s = _sessions.get(sid)
        if not s:
            abort(404, description="Unknown session id")
        s.begin()
        return jsonify({"ok": True, "depth": s.depth()})

    @app.post("/session/<sid>/commit")
    def commit_tx(sid):
        """Commit the top transaction layer (flush if outermost)."""
        s = _sessions.get(sid)
        if not s:
            abort(404, description="Unknown session id")
        try:
            s.commit()
            return jsonify({"ok": True, "depth": s.depth()})
        except RuntimeError as e:
            abort(400, description=str(e))

    @app.post("/session/<sid>/rollback")
    def rollback_tx(sid):
        """Discard the top transaction layer."""
        s = _sessions.get(sid)
        if not s:
            abort(404, description="Unknown session id")
        try:
            s.rollback()
            return jsonify({"ok": True, "depth": s.depth()})
        except RuntimeError as e:
            abort(400, description=str(e))

    @app.put("/store/<key>")
    def set_key(key):
        """
        Set or update a key with the provided JSON value.
        Request body must be: { "value": ... }
        """
        s = _get_session(request)
        data = request.get_json(force=True, silent=True) or {}
        if "value" not in data:
            abort(400, description="Missing 'value'")
        s.set(key, data["value"])
        return jsonify({"ok": True})

    @app.get("/store/<key>")
    def get_key(key):
        """
        Get a key's current value.
        Returns {key, value, found}, with HTTP 404 if missing.
        """
        s = _get_session(request)
        v = s.get(key)
        if v is None:
            return jsonify({"key": key, "value": None, "found": False}), 404
        return jsonify({"key": key, "value": v, "found": True})

    @app.delete("/store/<key>")
    def delete_key(key):
        """Delete a key (autocommit or within transaction)."""
        s = _get_session(request)
        s.delete(key)
        return jsonify({"ok": True})
    
    return app

if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=8000, debug=True)
