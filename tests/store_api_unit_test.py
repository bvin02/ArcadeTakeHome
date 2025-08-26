import pytest
from arcade_store.store import Store

# RUN USING python -m pytest -v

def test_basic_set_get_delete(tmp_path):
    db = tmp_path / "test.sqlite3"
    store = Store(str(db))

    s = store.new_session()
    assert s.get("a") is None

    s.set("a", 1)
    assert s.get("a") == 1

    s.delete("a")
    assert s.get("a") is None


def test_nested_transactions_commit(tmp_path):
    db = tmp_path / "test.sqlite3"
    store = Store(str(db))
    s = store.new_session()

    s.begin()
    s.set("x", 10)
    s.begin()
    s.set("x", 20)
    assert s.get("x") == 20
    s.commit()  # merge to parent
    assert s.get("x") == 20
    s.commit()  # flush to DB

    # New session sees committed value
    s2 = store.new_session()
    assert s2.get("x") == 20


def test_nested_transactions_rollback(tmp_path):
    db = tmp_path / "test.sqlite3"
    store = Store(str(db))
    s = store.new_session()

    s.begin()
    s.set("y", {"a": 1})
    s.begin()
    s.set("y", {"a": 2})
    assert s.get("y") == {"a": 2}
    s.rollback()  # discard inner change
    assert s.get("y") == {"a": 1}
    s.commit()  # commit outer
    assert store._db_get("y") == {"a": 1}


def test_delete_precedence(tmp_path):
    db = tmp_path / "test.sqlite3"
    store = Store(str(db))
    s = store.new_session()

    s.begin()
    s.set("k", "v")
    s.delete("k")
    assert s.get("k") is None
    s.commit()  # should result in no row in DB
    assert store._db_get("k") is None


def test_isolation_between_sessions(tmp_path):
    db = tmp_path / "test.sqlite3"
    store = Store(str(db))

    s1 = store.new_session()
    s2 = store.new_session()

    s1.begin()
    s1.set("z", 123)
    assert s1.get("z") == 123
    # s2 does not see uncommitted change
    assert s2.get("z") is None

    s1.commit()
    assert s2.get("z") == 123


def test_autocommit_when_no_tx(tmp_path):
    db = tmp_path / "test.sqlite3"
    store = Store(str(db))
    s = store.new_session()

    s.set("auto", True)  # no tx -> writes through
    s2 = store.new_session()
    assert s2.get("auto") is True


def test_rollback_errors(tmp_path):
    db = tmp_path / "test.sqlite3"
    store = Store(str(db))
    s = store.new_session()

    with pytest.raises(RuntimeError):
        s.rollback()
    with pytest.raises(RuntimeError):
        s.commit()


def test_large_values(tmp_path):
    db = tmp_path / "test.sqlite3"
    store = Store(str(db))
    s = store.new_session()

    big = {"blob": "x" * 10000, "list": list(range(1000))}
    s.begin()
    s.set("big", big)
    s.commit()

    assert store._db_get("big") == big