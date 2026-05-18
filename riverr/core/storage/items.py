from __future__ import annotations

import re
import time
from typing import Iterable

from ..models import Item, _item


def _html_to_markdown_safe(html: str) -> str:
    """Convert HTML to markdown via markdownify, falling back to plain
    text on any error. Used at upsert time to normalize RSS bodies so
    every fresh item is markdown going forward.
    """
    if not html:
        return ""
    s = html.strip()
    if not s:
        return ""
    # If there are no HTML tags at all, treat it as already-plain text.
    if "<" not in s or ">" not in s:
        return s
    try:
        from markdownify import markdownify as _md
        out = _md(html, heading_style="ATX", strip=["script", "style"])
        if out:
            out = re.sub(r"\n{3,}", "\n\n", out).strip()
            return out
    except Exception:
        pass
    return re.sub(r"<[^>]+>", " ", html).strip()


class ItemsMixin:
    def upsert_items(self, feed_id: int, items: Iterable[dict]) -> int:
        n_new = 0
        now = time.time()
        for it in items:
            existing = self.conn.execute(
                "SELECT id FROM items WHERE feed_id=? AND guid=?",
                (feed_id, it["guid"]),
            ).fetchone()
            if existing:
                continue
            raw_body = it.get("body") or ""
            body_md = _html_to_markdown_safe(raw_body) if raw_body else ""
            cur = self.conn.execute(
                """INSERT INTO items
                (feed_id, guid, title, author, link, comments_link, body, body_format, body_source, published_at, fetched_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    feed_id,
                    it["guid"],
                    it.get("title", ""),
                    it.get("author"),
                    it.get("link"),
                    it.get("comments_link"),
                    body_md,
                    "markdown",
                    "rss",
                    it.get("published_at"),
                    now,
                ),
            )
            self.conn.execute(
                "INSERT INTO read_state(item_id, read) VALUES (?, 0)", (cur.lastrowid,)
            )
            n_new += 1
        self.conn.commit()
        return n_new

    def clear_extracted(
        self,
        feed_filter: int | str | None = None,
        format_filter: str | None = None,
    ) -> int:
        """Clear extracted_body for items, optionally filtered by feed (id or
        URL) and/or body_format. Returns count of rows affected.
        """
        sql = "UPDATE items SET extracted_body=NULL WHERE extracted_body IS NOT NULL"
        params: list = []
        if feed_filter is not None:
            if isinstance(feed_filter, int) or (
                isinstance(feed_filter, str) and feed_filter.isdigit()
            ):
                sql += " AND feed_id=?"
                params.append(int(feed_filter))
            else:
                sql += " AND feed_id IN (SELECT id FROM feeds WHERE url=?)"
                params.append(feed_filter)
        if format_filter:
            sql += " AND body_format=?"
            params.append(format_filter)
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return cur.rowcount

    def reset_items(self, feed_filter: int | str | None = None) -> int:
        """Delete all items (and their read/starred state) so a refresh
        re-fetches them. Keeps feeds and other config. Returns count deleted.
        """
        sql_select = "SELECT id FROM items"
        params: list = []
        if feed_filter is not None:
            if isinstance(feed_filter, int) or (
                isinstance(feed_filter, str) and feed_filter.isdigit()
            ):
                sql_select += " WHERE feed_id=?"
                params.append(int(feed_filter))
            else:
                sql_select += " WHERE feed_id IN (SELECT id FROM feeds WHERE url=?)"
                params.append(feed_filter)
        ids = [r[0] for r in self.conn.execute(sql_select, params).fetchall()]
        if not ids:
            return 0
        ph = ",".join("?" * len(ids))
        self.conn.execute(f"DELETE FROM read_state WHERE item_id IN ({ph})", ids)
        # FTS sync happens via the items_ad trigger; do NOT manually delete
        # from items_fts here (the trigger fires on DELETE FROM items and the
        # double-write would clash with the external-content FTS5 contract,
        # producing "database disk image is malformed" on subsequent reads).
        cur = self.conn.execute(f"DELETE FROM items WHERE id IN ({ph})", ids)
        self.conn.commit()
        return cur.rowcount

    def prune_feed(self, feed_id: int, max_items: int) -> int:
        """Keep the most recent `max_items` non-starred items in a feed;
        delete the rest. Starred items are exempt from the cap (they are
        never deleted and don't count toward it). `max_items <= 0` disables
        pruning. Returns the number of rows deleted.
        """
        if max_items <= 0:
            return 0
        rows = self.conn.execute(
            """SELECT id FROM items
               WHERE feed_id=? AND starred=0
               ORDER BY COALESCE(published_at, fetched_at) DESC, id DESC""",
            (feed_id,),
        ).fetchall()
        if len(rows) <= max_items:
            return 0
        excess = [r["id"] for r in rows[max_items:]]
        ph = ",".join("?" * len(excess))
        self.conn.execute(
            f"DELETE FROM read_state WHERE item_id IN ({ph})", excess
        )
        cur = self.conn.execute(
            f"DELETE FROM items WHERE id IN ({ph})", excess
        )
        self.conn.commit()
        return cur.rowcount

    def items_for_feed(self, feed_id: int) -> list[Item]:
        rows = self.conn.execute(
            """SELECT items.*, COALESCE(read_state.read, 0) AS read
               FROM items LEFT JOIN read_state ON read_state.item_id = items.id
               WHERE feed_id=? ORDER BY COALESCE(published_at, fetched_at) DESC""",
            (feed_id,),
        ).fetchall()
        return [_item(r) for r in rows]

    def get_item(self, item_id: int) -> Item | None:
        r = self.conn.execute(
            """SELECT items.*, COALESCE(read_state.read, 0) AS read
               FROM items LEFT JOIN read_state ON read_state.item_id = items.id
               WHERE items.id=?""",
            (item_id,),
        ).fetchone()
        return _item(r) if r else None

    def set_extracted_body(
        self,
        item_id: int,
        body: str,
        body_format: str = "html",
        body_source: str | None = None,
    ) -> None:
        if body_source is None:
            self.conn.execute(
                "UPDATE items SET extracted_body=?, body_format=? WHERE id=?",
                (body, body_format, item_id),
            )
        else:
            self.conn.execute(
                "UPDATE items SET extracted_body=?, body_format=?, body_source=? WHERE id=?",
                (body, body_format, body_source, item_id),
            )
        self.conn.commit()

    def mark_read(self, item_id: int, read: bool = True) -> None:
        self.conn.execute(
            """INSERT INTO read_state(item_id, read, read_at) VALUES (?,?,?)
               ON CONFLICT(item_id) DO UPDATE SET read=excluded.read, read_at=excluded.read_at""",
            (item_id, 1 if read else 0, time.time() if read else None),
        )
        self.conn.commit()

    def mark_unread(self, item_id: int) -> None:
        self.mark_read(item_id, False)

    def mark_below_read(self, items: Iterable[Item]) -> int:
        n = 0
        for it in items:
            if not it.read:
                self.mark_read(it.id, True)
                it.read = True
                n += 1
        return n

    def set_starred(self, item_id: int, starred: bool) -> None:
        self.conn.execute(
            "UPDATE items SET starred=? WHERE id=?",
            (1 if starred else 0, item_id),
        )
        self.conn.commit()

    def is_starred(self, item_id: int) -> bool:
        r = self.conn.execute(
            "SELECT starred FROM items WHERE id=?", (item_id,)
        ).fetchone()
        return bool(r and r["starred"])

    def list_starred(self) -> list[Item]:
        rows = self.conn.execute(
            """SELECT items.*, COALESCE(read_state.read, 0) AS read
               FROM items LEFT JOIN read_state ON read_state.item_id = items.id
               WHERE starred=1
               ORDER BY COALESCE(published_at, fetched_at) DESC"""
        ).fetchall()
        return [_item(r) for r in rows]

    def mark_feed_read(self, feed_id: int) -> int:
        cur = self.conn.execute(
            """UPDATE read_state SET read=1, read_at=?
               WHERE item_id IN (SELECT id FROM items WHERE feed_id=?) AND read=0""",
            (time.time(), feed_id),
        )
        self.conn.commit()
        return cur.rowcount

    def unread_count(self, feed_id: int | None = None) -> int:
        if feed_id is None:
            r = self.conn.execute(
                """SELECT COUNT(*) AS c FROM items
                   LEFT JOIN read_state ON read_state.item_id = items.id
                   WHERE COALESCE(read_state.read, 0) = 0"""
            ).fetchone()
        else:
            r = self.conn.execute(
                """SELECT COUNT(*) AS c FROM items
                   LEFT JOIN read_state ON read_state.item_id = items.id
                   WHERE feed_id=? AND COALESCE(read_state.read, 0) = 0""",
                (feed_id,),
            ).fetchone()
        return r["c"]

    def new_since(self, ts: float, feed_id: int | None = None) -> int:
        if feed_id is None:
            r = self.conn.execute(
                "SELECT COUNT(*) AS c FROM items WHERE fetched_at > ?", (ts,)
            ).fetchone()
        else:
            r = self.conn.execute(
                "SELECT COUNT(*) AS c FROM items WHERE feed_id=? AND fetched_at > ?",
                (feed_id, ts),
            ).fetchone()
        return r["c"]
