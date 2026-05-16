from __future__ import annotations

from ..models import Feed, Item, _feed, _item
from .db import SCHEMA, StorageBase
from .feeds import FeedsMixin
from .fetch_log import FetchLogMixin
from .items import ItemsMixin, _html_to_markdown_safe
from .search import SearchMixin


class Storage(FeedsMixin, ItemsMixin, SearchMixin, FetchLogMixin, StorageBase):
    pass


__all__ = ["Storage", "Feed", "Item", "SCHEMA"]
