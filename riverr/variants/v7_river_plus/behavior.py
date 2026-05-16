"""Constants shared across v7 modules."""
from __future__ import annotations


VIEW_ALL = "all"
VIEW_FEED = "feed"
VIEW_STARRED = "starred"


_SOURCE_LABELS = {
    "rss": "feed rss → markdown",
    "trafilatura": "extracted markdown · trafilatura",
    "readability": "extracted markdown · readability",
    "legacy": "legacy html",
}
