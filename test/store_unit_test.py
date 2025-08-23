import json
from arcade_store.store import Store

# RUN USING python -m pytest -q

def test_isolation_and_commit(tmp_path):
    db_path = tmp_path / "demo.sqlite3"
    store = Store(str(db_path))
    s1 = store.new_session()
    s2 = store.new_session()

    # s1 writes inside a tx; s2 should not see it yet
    s1.begin()
    s1.set("a", {"n": 1})
    assert s1.get("a") == {"n": 1}
    assert s2.get("a") is None  # isolation

    # Commit outermost -> flush to DB; s2 now sees it
    s1.commit()
    assert s2.get("a") == {"n": 1}

def test_nested_transactions(tmp_path):
    db_path = tmp_path / "demo.sqlite3"
    store = Store(str(db_path))
    s1 = store.new_session()
    s2 = store.new_session()

    # Seed value
    s1.set("a", {"n": 1})
    assert s2.get("a") == {"n": 1}

    # Nested behavior
    s1.begin()
    s1.set("a", {"n": 2})
    s1.begin()
    s1.set("a", {"n": 3})
    assert s1.get("a") == {"n": 3}  # top layer visible to s1

    # Commit inner -> merge into parent
    s1.commit()
    assert s1.get("a") == {"n": 3}

    # Rollback outer -> discard both pending layers; DB unchanged
    s1.rollback()
    assert s2.get("a") == {"n": 1}
