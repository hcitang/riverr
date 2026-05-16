from __future__ import annotations

from typing import Iterable

from .storage import Item, Storage


def filter_items(items: Iterable[Item], query: str) -> list[Item]:
    q = query.strip().lower()
    if not q:
        return list(items)
    out: list[Item] = []
    for it in items:
        hay = " ".join([
            it.title or "",
            it.author or "",
            it.body or "",
            it.extracted_body or "",
        ]).lower()
        if q in hay:
            out.append(it)
    return out


def fts_search(storage: Storage, query: str, limit: int = 200) -> list[Item]:
    q = query.strip()
    if not q:
        return []
    return storage.search(q, limit=limit)
