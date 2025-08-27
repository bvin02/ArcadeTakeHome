import os
import time
import sqlite3
import json
import threading


class Store:
    """Holds the shared SQLite connection and provides helpers to access the DB."""

    def __init__(self, db_path=":memory:"):
        """
        Initialize the Store with an throwaway SQLite connection.

        Args:
            db_path (str, optional): Path to the SQLite database file.
                Defaults to ':memory:' for an in-memory database.

        Notes:
            - Uses `check_same_thread=False` to allow access across threads.
            - Sets `journal_mode=WAL` (Write-Ahead Logging) for better concurrent reads.
            - Ensures the `arcade_store` table exists with schema:
                - key   (TEXT, PRIMARY KEY)
                - value (TEXT)
        """
        self.log_path = "store_commits.txt"
        self._log_lock = threading.Lock()

        self.db_path = db_path
        self._tls = threading.local()

        init = sqlite3.connect(self.db_path, check_same_thread=False)
        # one-time init on a throwaway connection to create schema
        try:
            init.execute("PRAGMA journal_mode=WAL;")     # enables readers during writes
            init.execute("PRAGMA busy_timeout=3000;")    # wait up to 3s on locks
            init.execute(
                "CREATE TABLE IF NOT EXISTS arcade_store (key TEXT PRIMARY KEY, value TEXT)"
            )
            init.commit()
        finally:
            init.close()

    def _get_conn(self):
        """Return this thread's connection; creating it on first use."""
        conn = getattr(self._tls, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            # Re-apply pragmas on each new connection (journal_mode is db-level, others are per-conn)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout=3000;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            self._tls.conn = conn
        return conn
    
    # -- logging operations ---
    def _append_log(self, *, commit_type, writes, deletes):
        record = {
            "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "thread": threading.current_thread().name,
            "type": commit_type,           # "transaction" or "autocommit"
            "writes": writes,
            "deletes": sorted(deletes)
        }
        line = json.dumps(record, separators=(",", ":"))
        with self._log_lock:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    
    def print_log(self):
        """Return the entire commit log as plain text."""
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return ""

    # --- db operations via SQL queries ---
    def _db_get(self, key):
        """
        Retrieve a value from the database by its key.

        Args:
            key (str): The unique key to look up in the `arcade_store` table.

        Returns:
            Any | None: The deserialized value associated with the key,
            or None if the key does not exist.
        """
        conn = self._get_conn()
        query = conn.execute(
                    "SELECT value FROM arcade_store WHERE key = ?",
                    (key,))
        result = query.fetchone()
        if result is None:
            return None
        return json.loads(result[0])

    def _db_set(self, key, value):
        """
        Insert or update a key-value pair in the database.

        Args:
            key (str): The unique key to insert or update.
            value (Any): The value to store (will be serialized to JSON).

        Notes:
            - If the key already exists, its value is updated (upsert).
        """
        conn = self._get_conn()
        deserialized_value = json.dumps(value, separators=(",", ":"))
        conn.execute(
            "INSERT INTO arcade_store(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, deserialized_value),
        )

    def _db_delete(self, key):
        """
        Delete a key-value pair from the database.

        Args:
            key (str): The unique key to delete.

        Returns:
            None
        """
        conn = self._get_conn()
        conn.execute(
            "DELETE FROM arcade_store WHERE key = ?",
            (key,))

    # --- session management ---
    def new_session(self):
        """
        Create a new client session.

        Returns:
            Session: A session object that buffers reads/writes and supports
            nested transactions (BEGIN/COMMIT/ROLLBACK). Use this when you want
            to group multiple operations atomically or layer changes before
            flushing them to the database.
        """
        return Session(self)
    
    # --- dump entire committed db ---
    def print_db(self):
        """
        Return ALL committed (key, value) rows from the database.
        """
        conn = self._get_conn()
        db = conn.execute("SELECT key, value FROM arcade_store ORDER BY key").fetchall()
        return [(k, json.loads(v)) for (k, v) in db] 
    

class Session:
    """
    Per-client session with its own stack of nested transactions.

    The session keeps an in-memory stack of layers. Each layer holds:
      - `writes` (dict): keys and their pending values for this layer.
      - `deleted` (set): keys marked for deletion in this layer.

    Reads consult the stack from top to bottom before falling back to the DB.
    Writes/deletes go to the top layer when inside a transaction; otherwise
    they are applied immediately to the database (autocommit mode).

    Use:
        s = store.new_session()
        s.begin()
        s.set("k", 1)
        s.begin()
        s.set("k", 2)
        s.rollback()  # back to value 1 in the outer tx
        s.commit()    # flushes to DB
    """

    def __init__(self, store):
        """
        Initialize a session tied to a Store.

        Args:
            store (Store): The backing store that owns the SQLite connection.
        """
        self.store = store
        self._stack = []

    # --- Transaction control ---
    def begin(self):
        """
        Start a new (possibly nested) transaction layer.

        Notes:
            - Changes made after `begin()` are isolated in this layer until a
              matching `commit()` merges them or a `rollback()` discards them.
            - Layers can be nested arbitrarily; only the outermost commit
              touches the database.
        """
        self._stack.append(({}, set()))

    def commit(self):
        """
        Commit the current transaction layer.

        Behavior:
            - If there is a parent layer, merge this layer's pending writes and
              deletions into the parent without touching the database.
            - If this is the outermost layer, apply all pending writes/deletes
              to the database atomically in a single SQLite transaction.

        Raises:
            RuntimeError: If there is no active transaction to commit.
        """
        if not self._stack:
            raise RuntimeError("No active transaction to commit")
        top_writes, top_deleted = self._stack.pop()

        if self._stack:
            # Merge into parent layer
            parent_writes, parent_deleted = self._stack[-1]
            # Apply deletions to parent
            for k in top_deleted:
                parent_deleted.add(k)
                if k in parent_writes:
                    del parent_writes[k]
            # Apply writes to parent
            for k, v in top_writes.items():
                parent_writes[k] = v
                if k in parent_deleted:
                    parent_deleted.remove(k)
            return

        # Outermost: flush to DB atomically on a separate thread's connection
        conn = self.store._get_conn() 
        try:
            conn.execute("BEGIN;")
            for k in top_deleted:
                self.store._db_delete(k)
            for k, v in top_writes.items():
                self.store._db_set(k, v)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        
        self.store._append_log(
            commit_type="transaction",
            writes=top_writes,
            deletes=list(top_deleted),
        )

    def rollback(self):
        """
        Discard the current transaction layer without applying changes.

        Raises:
            RuntimeError: If there is no active transaction to roll back.
        """
        if not self._stack:
            raise RuntimeError("No active transaction to rollback")
        self._stack.pop()

    # --- Data operations (session-aware) ---
    def set(self, key, value):
        """
        Set (create or update) a key to a value.

        Args:
            key (str): The key to set.
            value (Any): The value to associate with the key.

        Notes:
            - Inside a transaction layer, the change is buffered until commit.
            - With no active transaction, the write is autocommitted to the DB.
        """
        if not self._stack:
            # autocommit
            conn = self.store._get_conn()
            self.store._db_set(key, value)
            conn.commit()
            self.store._append_log(
                commit_type="autocommit",
                writes={key: value},
                deletes=[]
            )
            return
        writes, deleted = self._stack[-1]
        writes[key] = value
        if key in deleted:
            deleted.remove(key)

    def get(self, key):
        """
        Get the current value for a key, considering uncommitted changes.

        Args:
            key (str): The key to look up.

        Returns:
            Any | None: The value if present (including from pending writes),
            or None if deleted in any active layer or absent from the database.
        """
        # Search from top layer down
        for writes, deleted in reversed(self._stack):
            if key in deleted:
                return None
            if key in writes:
                return writes[key]
        # Fallback to DB
        return self.store._db_get(key)

    def delete(self, key):
        """
        Mark a key as deleted (or delete immediately with autocommit).

        Args:
            key (str): The key to delete.

        Notes:
            - Inside a transaction, the deletion is recorded in the top layer
              and will take effect on commit.
            - With no active transaction, the deletion is autocommitted.
        """
        if not self._stack:
            conn = self.store._get_conn()
            self.store._db_delete(key)
            conn.commit()
            self.store._append_log(
                commit_type="autocommit",
                writes={},
                deletes=[key]
            )
            return
        writes, deleted = self._stack[-1]
        deleted.add(key)
        if key in writes:
            del writes[key]
    
    # --- Utility ---
    def depth(self):
        """
        Return the current transaction nesting depth.

        Returns:
            int: Number of active transaction layers (0 means autocommit mode).
        """
        return len(self._stack)