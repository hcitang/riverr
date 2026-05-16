from __future__ import annotations

import time


class FetchLogMixin:
    def log_fetch(self, feed_id: int, ok: bool, new_count: int, error: str | None = None) -> None:
        self.conn.execute(
            "INSERT INTO fetch_log(feed_id, at, ok, new_count, error) VALUES (?,?,?,?,?)",
            (feed_id, time.time(), 1 if ok else 0, new_count, error),
        )
        self.conn.commit()

    def last_fetch_at(self) -> float | None:
        r = self.conn.execute("SELECT MAX(at) AS m FROM fetch_log").fetchone()
        return r["m"] if r and r["m"] else None

    def previous_refresh_at(self) -> float | None:
        """Second-most-recent fetch timestamp across all feeds.

        Used to draw a "previous refresh" divider: items newer than this
        appeared in the latest refresh; items older were already known.
        """
        # Get the per-refresh-tick timestamps. fetch_log gets one row per
        # feed per refresh; group close-in-time rows by rounding to whole
        # seconds and take the two most recent distinct ticks.
        rows = self.conn.execute(
            "SELECT DISTINCT CAST(at AS INTEGER) AS t FROM fetch_log "
            "ORDER BY t DESC LIMIT 2"
        ).fetchall()
        if len(rows) < 2:
            return None
        return float(rows[1]["t"])
