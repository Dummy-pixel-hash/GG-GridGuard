"""
SQLite connection factory for GridGuard.

Usage
-----
    from storage.connection import get_connection

    conn = get_connection()                    # uses in-memory DB (tests)
    conn = get_connection("gridguard.db")      # on-disk, production / demo
    conn = get_connection(":memory:")          # explicit in-memory

The connection is configured with:
- WAL journal mode (concurrent reads, single writer)
- PRAGMA foreign_keys = ON
- Row factory set to sqlite3.Row for dict-like access
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

_DEFAULT_DB_PATH = ":memory:"


def get_connection(path: str | Path = _DEFAULT_DB_PATH) -> sqlite3.Connection:
    """
    Open (or create) a SQLite database at *path* and return the connection.

    Parameters
    ----------
    path:
        File-system path to the SQLite database file, or the special string
        ``:memory:`` for a transient in-memory database.  Defaults to
        ``:memory:`` so tests need no teardown.

    Returns
    -------
    sqlite3.Connection
        Configured with WAL mode, foreign keys enabled, and row_factory set
        to ``sqlite3.Row``.
    """
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
