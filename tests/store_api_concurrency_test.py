import threading
import time
from typing import List
from arcade_store.store import Store

# RUN USING python -m pytest -v

# Notes:
# - Each thread uses its own SQLite connection (thread-local in Store).
# - SQLite (with WAL mode) allows many concurrent readers but only one writer at a time.
# - These tests verify transaction isolation, atomic commit behavior, and last-write-wins semantics.


def test_isolation_across_threads(tmp_path):
    db = tmp_path / "concurrency.sqlite3"
    store = Store(str(db))

    s1 = store.new_session()
    s2 = store.new_session()

    s1.begin()
    s1.set("a", 1)

    ready = threading.Event()
    seen = {"before": None, "after": None}

    def reader():
        # Signal that we’re about to read before writer commits
        ready.set()
        # Before commit: s2 should not see s1's uncommitted change
        seen["before"] = s2.get("a")

        # Wait as writer commits
        time.sleep(0.05)
        seen["after"] = s2.get("a")

    t = threading.Thread(target=reader)
    t.start()

    ready.wait()
    time.sleep(0.02)
    s1.commit()

    t.join()

    assert seen["before"] is None
    assert seen["after"] == 1


def test_atomic_outer_commit_all_or_nothing(tmp_path):
    db = tmp_path / "atomic.sqlite3"
    store = Store(str(db))

    s_writer = store.new_session()
    s_reader = store.new_session()

    N = 200
    keys = [f"k{i}" for i in range(N)]

    # Stage a lot of writes
    s_writer.begin()
    for i, k in enumerate(keys):
        s_writer.set(k, i)

    # Reader samples before and after commit
    before_after = {"before": 0, "after": 0}

    def reader():
        # Count how many keys are visible before commit
        before = 0
        for k in keys:
            if s_reader.get(k) is not None:
                before += 1
        before_after["before"] = before

        # Give writer time to commit
        time.sleep(0.05)

        after = 0
        for k in keys:
            if s_reader.get(k) is not None:
                after += 1
        before_after["after"] = after

    t = threading.Thread(target=reader)
    t.start()

    time.sleep(0.01)  # ensure reader does the first pass pre-commit
    s_writer.commit()

    t.join()

    # All-or-none visibility: before=0, after=N
    assert before_after["before"] == 0
    assert before_after["after"] == N


def test_two_writers_interleaving_last_write_wins(tmp_path):
    db = tmp_path / "writers.sqlite3"
    store = Store(str(db))

    s1 = store.new_session()
    s2 = store.new_session()

    start = threading.Barrier(2)

    def w1():
        start.wait()
        # Autocommit write (no explicit tx)
        s1.set("x", "one")

    def w2():
        start.wait()
        # Delay slightly so this write happens after w1
        time.sleep(0.02)
        s2.set("x", "two")

    t1 = threading.Thread(target=w1)
    t2 = threading.Thread(target=w2)
    t1.start(); t2.start()
    t1.join(); t2.join()

    # The later write should win
    s_check = store.new_session()
    assert s_check.get("x") == "two"


def test_many_writers_different_keys(tmp_path):
    db = tmp_path / "many.sqlite3"
    store = Store(str(db))

    NUM_THREADS = 16
    PER_THREAD = 50

    def writer(tid: int):
        s = store.new_session()
        for i in range(PER_THREAD):
            key = f"t{tid}:{i}"
            s.set(key, {"tid": tid, "i": i})

    threads: List[threading.Thread] = []
    for t in range(NUM_THREADS):
        th = threading.Thread(target=writer, args=(t,))
        th.start()
        threads.append(th)

    for th in threads:
        th.join()

    # Validate all expected keys exist with the correct values
    s_check = store.new_session()
    total = 0
    for t in range(NUM_THREADS):
        for i in range(PER_THREAD):
            key = f"t{t}:{i}"
            v = s_check.get(key)
            assert v == {"tid": t, "i": i}
            total += 1
    assert total == NUM_THREADS * PER_THREAD
