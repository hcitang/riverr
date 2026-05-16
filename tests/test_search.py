from riverr.core.search import filter_items, fts_search
from riverr.core.storage import Item


def _item(**kw):
    base = dict(
        id=1, feed_id=1, guid="g", title="t", author=None, link=None,
        comments_link=None, body=None, extracted_body=None,
        published_at=None, fetched_at=0.0, read=False,
    )
    base.update(kw)
    return Item(**base)


def test_filter_in_memory():
    items = [
        _item(id=1, title="Apples are red", body=""),
        _item(id=2, title="Bananas are yellow", body=""),
        _item(id=3, title="Cherries", body="full of antioxidants"),
    ]
    out = filter_items(items, "yellow")
    assert [i.id for i in out] == [2]
    out = filter_items(items, "ANTIOX")
    assert [i.id for i in out] == [3]
    out = filter_items(items, "")
    assert len(out) == 3


def test_fts(tmp_storage):
    fid = tmp_storage.add_feed("https://e.com/rss", "E")
    tmp_storage.upsert_items(fid, [
        {"guid": "1", "title": "Singapore housing scheme", "body": "details about HDB", "link": "u"},
        {"guid": "2", "title": "Mac performance", "body": "apple silicon", "link": "u"},
    ])
    hits = fts_search(tmp_storage, "housing")
    assert len(hits) == 1
    hits = fts_search(tmp_storage, "")
    assert hits == []
