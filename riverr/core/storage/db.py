from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS feeds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    display_title TEXT,
    site_url TEXT,
    added_at REAL NOT NULL,
    last_fetched_at REAL,
    abbrev TEXT,
    color TEXT
);

CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feed_id INTEGER NOT NULL REFERENCES feeds(id) ON DELETE CASCADE,
    guid TEXT NOT NULL,
    title TEXT NOT NULL,
    author TEXT,
    link TEXT,
    comments_link TEXT,
    body TEXT,
    extracted_body TEXT,
    body_format TEXT NOT NULL DEFAULT 'html',
    body_source TEXT NOT NULL DEFAULT 'legacy',
    published_at REAL,
    fetched_at REAL NOT NULL,
    starred INTEGER NOT NULL DEFAULT 0,
    UNIQUE(feed_id, guid)
);
CREATE INDEX IF NOT EXISTS idx_items_feed ON items(feed_id, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_items_fetched ON items(fetched_at);

CREATE TABLE IF NOT EXISTS read_state (
    item_id INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
    read INTEGER NOT NULL DEFAULT 0,
    read_at REAL
);

CREATE TABLE IF NOT EXISTS fetch_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feed_id INTEGER NOT NULL REFERENCES feeds(id) ON DELETE CASCADE,
    at REAL NOT NULL,
    ok INTEGER NOT NULL,
    new_count INTEGER NOT NULL DEFAULT 0,
    error TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
    title, author, body, content='items', content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS items_ai AFTER INSERT ON items BEGIN
    INSERT INTO items_fts(rowid, title, author, body)
    VALUES (new.id, new.title, coalesce(new.author,''), coalesce(new.extracted_body, new.body, ''));
END;
CREATE TRIGGER IF NOT EXISTS items_ad AFTER DELETE ON items BEGIN
    INSERT INTO items_fts(items_fts, rowid, title, author, body)
    VALUES ('delete', old.id, old.title, coalesce(old.author,''), coalesce(old.extracted_body, old.body, ''));
END;
CREATE TRIGGER IF NOT EXISTS items_au AFTER UPDATE ON items BEGIN
    INSERT INTO items_fts(items_fts, rowid, title, author, body)
    VALUES ('delete', old.id, old.title, coalesce(old.author,''), coalesce(old.extracted_body, old.body, ''));
    INSERT INTO items_fts(rowid, title, author, body)
    VALUES (new.id, new.title, coalesce(new.author,''), coalesce(new.extracted_body, new.body, ''));
END;
"""


class StorageBase:
    def __init__(self, db_path: Path | str):
        self.db_path = str(db_path)
        self.conn = sqlite3.connect(self.db_path, timeout=10.0)
        self.conn.row_factory = sqlite3.Row
        # WAL allows safe concurrent readers + one writer across processes
        # (e.g. `riverr v7` running while `riverr remove` fires in
        # another shell). Default rollback-journal mode corrupted the DB
        # when both touched the file at once.
        try:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.execute("PRAGMA busy_timeout=5000")
        except sqlite3.DatabaseError:
            pass
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        # Add columns added after initial release if missing.
        item_cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(items)")}
        if "starred" not in item_cols:
            self.conn.execute(
                "ALTER TABLE items ADD COLUMN starred INTEGER NOT NULL DEFAULT 0"
            )
        feed_cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(feeds)")}
        if "abbrev" not in feed_cols:
            self.conn.execute("ALTER TABLE feeds ADD COLUMN abbrev TEXT")
        if "color" not in feed_cols:
            self.conn.execute("ALTER TABLE feeds ADD COLUMN color TEXT")
        if "body_format" not in item_cols:
            self.conn.execute(
                "ALTER TABLE items ADD COLUMN body_format TEXT NOT NULL DEFAULT 'html'"
            )
        if "body_source" not in item_cols:
            self.conn.execute(
                "ALTER TABLE items ADD COLUMN body_source TEXT NOT NULL DEFAULT 'legacy'"
            )
        self._migrate_html_bodies_to_markdown()

    def _migrate_html_bodies_to_markdown(self) -> None:
        """One-shot: convert any items with body_format in ('html','legacy')
        to markdown via markdownify, in place. Idempotent — rows already at
        'markdown' are skipped."""
        try:
            rows = self.conn.execute(
                "SELECT id, body, extracted_body FROM items "
                "WHERE body_format IN ('html', 'legacy')"
            ).fetchall()
        except sqlite3.DatabaseError:
            return
        if not rows:
            return
        try:
            from markdownify import markdownify as _md
        except Exception:
            return
        import re as _re

        def _convert(html: str) -> str:
            try:
                out = _md(html, heading_style="ATX", strip=["script", "style"])
            except Exception:
                return html
            if not out:
                return html
            return _re.sub(r"\n{3,}", "\n\n", out).strip()

        cur = self.conn.cursor()
        try:
            for r in rows:
                item_id = r["id"]
                body = r["body"] or ""
                extracted = r["extracted_body"] or ""
                new_body = _convert(body) if body else body
                new_extracted = _convert(extracted) if extracted else extracted
                cur.execute(
                    "UPDATE items SET body=?, extracted_body=?, body_format='markdown' "
                    "WHERE id=?",
                    (new_body, new_extracted, item_id),
                )
            self.conn.commit()
        except sqlite3.DatabaseError:
            self.conn.rollback()

    def close(self) -> None:
        self.conn.close()

    # --- maintenance / observability ---

    def db_size_bytes(self) -> int:
        """Total on-disk size of the SQLite database file plus its WAL
        and shared-memory sidecars (so the number doesn't appear to
        shrink/grow as WAL checkpoints fire)."""
        total = 0
        for suffix in ("", "-wal", "-shm"):
            try:
                total += Path(self.db_path + suffix).stat().st_size
            except OSError:
                pass
        return total

    def optimize_fts(self) -> None:
        try:
            self.conn.execute("INSERT INTO items_fts(items_fts) VALUES('optimize')")
            self.conn.commit()
        except sqlite3.DatabaseError:
            pass

    def vacuum(self) -> None:
        """Reclaim pages freed by deletes. No-op on error (e.g. open txn)."""
        try:
            self.conn.commit()
            self.conn.isolation_level = None
            try:
                self.conn.execute("VACUUM")
            finally:
                self.conn.isolation_level = ""
        except sqlite3.DatabaseError:
            pass
