import sqlite3
from contextlib import closing

import pytest
from sqlalchemy import create_engine

from nextpanel import migrations, models

# The first release's requests table: identical columns, but provider ids
# were unique per media type regardless of provider.
LEGACY_REQUESTS = migrations._REQUESTS_V1.replace(
    "UNIQUE (media_type, provider, provider_id)", "UNIQUE (media_type, provider_id)"
)
ROW = (
    "INSERT INTO requests (user_id, media_type, provider, provider_id, title, english_title,"
    " alt_titles, cover_url, description, status, note, downloaded_count, total_count,"
    " created_at, updated_at) VALUES (1, 'MANGA', ?, ?, ?, '', '', '', '', ?, '', 0, 0,"
    " '2026-01-01', '2026-01-01')"
)


def legacy_database(path):
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR)")
        conn.execute(LEGACY_REQUESTS)
        conn.execute("CREATE INDEX ix_requests_user_id ON requests (user_id)")
        conn.execute("INSERT INTO users VALUES (1, 'admin')")
        conn.execute(ROW, ("mangaupdates", 111, "One Piece", "AVAILABLE"))
        conn.execute(ROW, ("anilist", 222, "Dandadan", "PENDING"))
        conn.commit()


def schema(conn, table):
    # ADD COLUMN appends, so only the order may differ from create_all's
    columns = sorted(row[1:] for row in conn.execute(f"PRAGMA table_info({table})"))
    return columns, sorted(migrations._unique_column_sets(conn, table)), sorted(
        row[1] for row in conn.execute(f"PRAGMA index_list({table})")
        if not row[1].startswith("sqlite_autoindex")
    )


def test_legacy_database_is_upgraded(tmp_path):
    db = tmp_path / "nextpanel.db"
    legacy_database(db)

    migrations.migrate(db)

    with closing(sqlite3.connect(db)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == migrations.LATEST
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        rows = conn.execute(
            "SELECT title, status, available_notified FROM requests ORDER BY id"
        ).fetchall()
        # complete requests were already announced by the old release
        assert rows == [("One Piece", "AVAILABLE", 1), ("Dandadan", "PENDING", 0)]
        # an AniList id may now equal an unrelated MangaUpdates id
        conn.execute(ROW, ("anilist", 111, "Other", "PENDING"))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(ROW, ("anilist", 111, "Duplicate", "PENDING"))

    backup = tmp_path / "nextpanel-v0-backup.db"
    with closing(sqlite3.connect(backup)) as conn:
        assert conn.execute("SELECT count(*) FROM requests").fetchone()[0] == 2
        assert ("media_type", "provider_id") in migrations._unique_column_sets(conn, "requests")


def test_upgraded_schema_matches_a_new_database(tmp_path):
    upgraded = tmp_path / "upgraded.db"
    legacy_database(upgraded)
    migrations.migrate(upgraded)

    fresh = tmp_path / "fresh.db"
    engine = create_engine(f"sqlite:///{fresh}")
    models.Base.metadata.create_all(engine)
    engine.dispose()

    with closing(sqlite3.connect(upgraded)) as a, closing(sqlite3.connect(fresh)) as b:
        assert schema(a, "requests") == schema(b, "requests")


def test_new_database_is_left_to_create_all(tmp_path):
    db = tmp_path / "nextpanel.db"
    migrations.migrate(db)
    with closing(sqlite3.connect(db)) as conn:
        assert not migrations._table_exists(conn, "requests")
    assert not list(tmp_path.glob("*backup*"))


def test_current_database_is_not_touched(tmp_path):
    db = tmp_path / "nextpanel.db"
    legacy_database(db)
    migrations.migrate(db)
    (tmp_path / "nextpanel-v0-backup.db").unlink()

    migrations.migrate(db)
    assert not list(tmp_path.glob("*backup*"))


def test_failed_step_rolls_back_only_itself(tmp_path, monkeypatch):
    db = tmp_path / "nextpanel.db"
    legacy_database(db)

    def broken(conn):
        conn.execute("ALTER TABLE requests ADD COLUMN half_done INTEGER")
        raise RuntimeError("boom")

    monkeypatch.setattr(
        migrations, "MIGRATIONS", [migrations._v1_request_uniqueness_includes_provider, broken]
    )
    monkeypatch.setattr(migrations, "LATEST", 2)
    with pytest.raises(RuntimeError):
        migrations.migrate(db)

    with closing(sqlite3.connect(db)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        assert "half_done" not in migrations._columns(conn, "requests")
        assert ("media_type", "provider", "provider_id") in (
            migrations._unique_column_sets(conn, "requests")
        )
