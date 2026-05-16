from __future__ import annotations

import sqlite3

from ..models import Item, _item


class SearchMixin:
    def search(self, query: str, limit: int = 200) -> list[Item]:
        try:
            rows = self.conn.execute(
                """SELECT items.*, COALESCE(read_state.read, 0) AS read
                   FROM items_fts
                   JOIN items ON items.id = items_fts.rowid
                   LEFT JOIN read_state ON read_state.item_id = items.id
                   WHERE items_fts MATCH ?
                   ORDER BY rank LIMIT ?""",
                (query, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [_item(r) for r in rows]
