"""Versioned, in-place upgrades for existing SQLite databases.

`create_all` only creates missing tables; it never changes a table that
already exists. Each step below upgrades a database created by an older
release by one version, and SQLite's `user_version` records the last step
applied. A new database is created at the current schema by `create_all`
and stamped with LATEST, so the steps only ever run against old files.

Databases from before this runner existed report version 0 whatever shape
they are in, so every step checks the actual schema before changing it.
Each step runs in its own transaction together with its version bump, and
the file is backed up once before the first pending step.

To change the schema: update the model, then append a step here that brings
an existing database to the same shape. Never edit a released step.
"""

import logging
import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

log = logging.getLogger(__name__)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return row is not None


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def _unique_column_sets(conn: sqlite3.Connection, table: str) -> list[tuple[str, ...]]:
    sets = []
    for index in conn.execute(f"PRAGMA index_list({table})").fetchall():
        name, unique = index[1], index[2]
        if unique:
            sets.append(tuple(row[2] for row in conn.execute(f"PRAGMA index_info('{name}')")))
    return sets


# The requests table exactly as of version 1. Later steps alter this shape;
# they must not be folded back into it.
_REQUESTS_V1 = """
CREATE TABLE requests (
    id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    media_type VARCHAR(5) NOT NULL,
    provider VARCHAR NOT NULL,
    provider_id INTEGER NOT NULL,
    title VARCHAR NOT NULL,
    english_title VARCHAR NOT NULL,
    alt_titles TEXT NOT NULL,
    year INTEGER,
    cover_url VARCHAR NOT NULL,
    description TEXT NOT NULL,
    status VARCHAR(19) NOT NULL,
    note TEXT NOT NULL,
    remote_series_id INTEGER,
    downloaded_count INTEGER NOT NULL,
    total_count INTEGER NOT NULL,
    decided_by_id INTEGER,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT ux_requests_media_provider UNIQUE (media_type, provider, provider_id),
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY(decided_by_id) REFERENCES users (id) ON DELETE SET NULL
)
"""


def _v1_request_uniqueness_includes_provider(conn: sqlite3.Connection) -> None:
    """The first release made (media_type, provider_id) unique, so an AniList
    id could collide with an unrelated MangaUpdates id of the same number.
    SQLite cannot drop a table constraint; rebuild the table instead."""
    if ("media_type", "provider_id") not in _unique_column_sets(conn, "requests"):
        return
    columns = ", ".join(_columns(conn, "requests"))
    conn.execute(_REQUESTS_V1.replace("CREATE TABLE requests", "CREATE TABLE _requests_v1"))
    conn.execute(f"INSERT INTO _requests_v1 ({columns}) SELECT {columns} FROM requests")
    conn.execute("DROP TABLE requests")
    conn.execute("ALTER TABLE _requests_v1 RENAME TO requests")
    conn.execute("CREATE INDEX ix_requests_user_id ON requests (user_id)")


def _v2_request_available_notified(conn: sqlite3.Connection) -> None:
    if "available_notified" in _columns(conn, "requests"):
        return
    conn.execute(
        "ALTER TABLE requests ADD COLUMN available_notified BOOLEAN NOT NULL DEFAULT 0"
    )
    # Requests that are already complete were announced by the old code.
    conn.execute("UPDATE requests SET available_notified = 1 WHERE status = 'AVAILABLE'")


MIGRATIONS: list[Callable[[sqlite3.Connection], None]] = [
    _v1_request_uniqueness_includes_provider,
    _v2_request_available_notified,
]
LATEST = len(MIGRATIONS)


def _backup(conn: sqlite3.Connection, db_path: Path, version: int) -> Path:
    target = db_path.with_name(f"{db_path.stem}-v{version}-backup{db_path.suffix}")
    with closing(sqlite3.connect(target)) as copy:
        conn.backup(copy)
    return target


def migrate(db_path: Path) -> None:
    """Bring an existing database up to LATEST. Blocking; run at startup
    before the application opens its own connections."""
    with closing(sqlite3.connect(db_path, isolation_level=None)) as conn:
        # Persistent per file: readers no longer wait for the poll job's or a
        # webhook's write to finish, and vice versa.
        conn.execute("PRAGMA journal_mode=WAL")
        if not _table_exists(conn, "requests"):
            return  # new database; create_all builds the current schema
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > LATEST:
            log.warning(
                "database schema v%d is newer than this release (v%d)", version, LATEST
            )
            return
        if version == LATEST:
            return
        backup = _backup(conn, db_path, version)
        log.info("upgrading database from v%d to v%d (backup: %s)", version, LATEST, backup)
        for number in range(version + 1, LATEST + 1):
            conn.execute("BEGIN IMMEDIATE")
            try:
                MIGRATIONS[number - 1](conn)
                conn.execute(f"PRAGMA user_version = {number}")
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
