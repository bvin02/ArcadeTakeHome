import sqlite3
import json


class Store:
    """Holds the shared SQLite connection and provides helpers to access the DB."""

    def __init__(self, db_path=":memory:"):
        """
        Initialize the Store with an SQLite connection.

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
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS arcade_store (key TEXT PRIMARY KEY, value TEXT)"
        )
        self.conn.commit()

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
        query = self.conn.execute("SELECT value FROM arcade_store WHERE key = ?",
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
        deserialized_value = json.dumps(value, separators=(",", ":"))
        self.conn.execute(
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
        self.conn.execute("DELETE FROM arcade_store WHERE key = ?",
                          (key,))
