from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional


@dataclass
class Feed:
    id: int
    url: str
    title: str
    display_title: Optional[str]
    site_url: Optional[str]
    added_at: float
    last_fetched_at: Optional[float]
    abbrev: Optional[str] = None
    color: Optional[str] = None

    @property
    def name(self) -> str:
        return self.display_title or self.title


@dataclass
class Item:
    id: int
    feed_id: int
    guid: str
    title: str
    author: Optional[str]
    link: Optional[str]
    comments_link: Optional[str]
    body: Optional[str]
    extracted_body: Optional[str]
    published_at: Optional[float]
    fetched_at: float
    read: bool = False
    starred: bool = False
    body_format: str = "html"
    body_source: str = "legacy"


def _feed(r: sqlite3.Row) -> Feed:
    keys = r.keys()
    return Feed(
        id=r["id"], url=r["url"], title=r["title"],
        display_title=r["display_title"], site_url=r["site_url"],
        added_at=r["added_at"], last_fetched_at=r["last_fetched_at"],
        abbrev=r["abbrev"] if "abbrev" in keys else None,
        color=r["color"] if "color" in keys else None,
    )


def _item(r: sqlite3.Row) -> Item:
    keys = r.keys()
    return Item(
        id=r["id"], feed_id=r["feed_id"], guid=r["guid"],
        title=r["title"], author=r["author"], link=r["link"],
        comments_link=r["comments_link"], body=r["body"],
        extracted_body=r["extracted_body"],
        published_at=r["published_at"], fetched_at=r["fetched_at"],
        read=bool(r["read"]) if "read" in keys else False,
        starred=bool(r["starred"]) if "starred" in keys else False,
        body_format=(r["body_format"] if "body_format" in keys and r["body_format"] else "html"),
        body_source=(r["body_source"] if "body_source" in keys and r["body_source"] else "legacy"),
    )
