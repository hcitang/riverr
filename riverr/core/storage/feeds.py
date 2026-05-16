from __future__ import annotations

import time

from ..models import Feed, _feed


class FeedsMixin:
    def add_feed(self, url: str, title: str, site_url: str | None = None) -> int:
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO feeds(url, title, site_url, added_at) VALUES (?,?,?,?)",
            (url, title, site_url, time.time()),
        )
        self.conn.commit()
        if cur.lastrowid:
            return cur.lastrowid
        row = self.conn.execute("SELECT id FROM feeds WHERE url=?", (url,)).fetchone()
        return row["id"]

    def list_feeds(self) -> list[Feed]:
        rows = self.conn.execute("SELECT * FROM feeds ORDER BY id").fetchall()
        return [_feed(r) for r in rows]

    def get_feed(self, feed_id: int) -> Feed | None:
        r = self.conn.execute("SELECT * FROM feeds WHERE id=?", (feed_id,)).fetchone()
        return _feed(r) if r else None

    def rename_feed(self, feed_id: int, display_title: str) -> None:
        self.conn.execute(
            "UPDATE feeds SET display_title=? WHERE id=?", (display_title, feed_id)
        )
        self.conn.commit()

    def set_abbrev(self, feed_id: int, abbrev: str | None) -> None:
        self.conn.execute(
            "UPDATE feeds SET abbrev=? WHERE id=?", (abbrev, feed_id)
        )
        self.conn.commit()

    def set_color(self, feed_id: int, color: str | None) -> None:
        self.conn.execute(
            "UPDATE feeds SET color=? WHERE id=?", (color, feed_id)
        )
        self.conn.commit()

    def get_color(self, feed_id: int) -> str | None:
        r = self.conn.execute(
            "SELECT color FROM feeds WHERE id=?", (feed_id,)
        ).fetchone()
        return r["color"] if r and "color" in r.keys() else None

    def set_last_fetched(self, feed_id: int, ts: float) -> None:
        self.conn.execute(
            "UPDATE feeds SET last_fetched_at=? WHERE id=?", (ts, feed_id)
        )
        self.conn.commit()

    def remove_feed(self, feed: int | str) -> int:
        """Delete a feed by id or URL, plus all its items and read state.
        Returns 1 if a feed was removed, 0 if not found."""
        if isinstance(feed, int) or (isinstance(feed, str) and feed.isdigit()):
            row = self.conn.execute(
                "SELECT id FROM feeds WHERE id=?", (int(feed),)
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT id FROM feeds WHERE url=? OR title=? OR display_title=?",
                (feed, feed, feed),
            ).fetchone()
        if not row:
            return 0
        fid = row[0]
        item_ids = [
            r[0] for r in self.conn.execute(
                "SELECT id FROM items WHERE feed_id=?", (fid,)
            ).fetchall()
        ]
        if item_ids:
            ph = ",".join("?" * len(item_ids))
            self.conn.execute(f"DELETE FROM read_state WHERE item_id IN ({ph})", item_ids)
            # FTS sync via items_ad trigger; see items.reset_items for context.
            self.conn.execute(f"DELETE FROM items WHERE id IN ({ph})", item_ids)
        self.conn.execute("DELETE FROM fetch_log WHERE feed_id=?", (fid,))
        self.conn.execute("DELETE FROM feeds WHERE id=?", (fid,))
        self.conn.commit()
        return 1
