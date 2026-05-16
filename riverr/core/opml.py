from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
import xml.etree.ElementTree as ET


# Extension namespace for riverr-specific attributes (abbrev, color, durable
# display title). Written to <opml xmlns:fr="..."> and read back if present.
FR_NS = "https://github.com/riverr/riverr"
FR_PREFIX = "fr"
ET.register_namespace(FR_PREFIX, FR_NS)
_FR_ABBREV = f"{{{FR_NS}}}abbrev"
_FR_COLOR = f"{{{FR_NS}}}color"
_FR_DISPLAY = f"{{{FR_NS}}}displayTitle"


@dataclass
class OpmlEntry:
    title: str
    xml_url: str
    html_url: str | None = None
    abbrev: str | None = None
    color: str | None = None


def _entry_from_outline(o: ET.Element) -> OpmlEntry | None:
    xml_url = o.attrib.get("xmlUrl")
    if not xml_url:
        return None
    # Prefer the durable fr:displayTitle, then standard title/text, then URL.
    title = (
        o.attrib.get(_FR_DISPLAY)
        or o.attrib.get("title")
        or o.attrib.get("text")
        or xml_url
    )
    return OpmlEntry(
        title=title,
        xml_url=xml_url,
        html_url=o.attrib.get("htmlUrl"),
        abbrev=o.attrib.get(_FR_ABBREV),
        color=o.attrib.get(_FR_COLOR),
    )


def parse(path: Path | str) -> list[OpmlEntry]:
    tree = ET.parse(str(path))
    root = tree.getroot()
    out: list[OpmlEntry] = []
    for o in root.iter("outline"):
        e = _entry_from_outline(o)
        if e is not None:
            out.append(e)
    return out


def parse_string(s: str) -> list[OpmlEntry]:
    root = ET.fromstring(s)
    out: list[OpmlEntry] = []
    for o in root.iter("outline"):
        e = _entry_from_outline(o)
        if e is not None:
            out.append(e)
    return out


def write(entries: Iterable[OpmlEntry], path: Path | str) -> None:
    Path(path).write_text(to_string(entries), encoding="utf-8")


def to_string(entries: Iterable[OpmlEntry]) -> str:
    opml = ET.Element("opml", {"version": "2.0"})
    head = ET.SubElement(opml, "head")
    ET.SubElement(head, "title").text = "riverr subscriptions"
    body = ET.SubElement(opml, "body")
    for e in entries:
        attrib = _entry_attrib(e)
        ET.SubElement(body, "outline", attrib=attrib)
    ET.indent(opml, space="  ")
    return ET.tostring(opml, encoding="unicode", xml_declaration=True) + "\n"


def _entry_attrib(e: OpmlEntry) -> dict[str, str]:
    a: dict[str, str] = {
        "type": "rss",
        "text": e.title,
        "title": e.title,
        "xmlUrl": e.xml_url,
    }
    if e.html_url:
        a["htmlUrl"] = e.html_url
    # Durable display title — survives if a future writer rewrites `text`/`title`
    # from upstream feed metadata.
    a[_FR_DISPLAY] = e.title
    if e.abbrev:
        a[_FR_ABBREV] = e.abbrev
    if e.color:
        a[_FR_COLOR] = e.color
    return a


# --- sync helpers ---

def _load_or_empty(opml_path: Path | str) -> list[OpmlEntry]:
    p = Path(opml_path)
    if p.exists():
        return parse(p)
    return []


def add_entry(opml_path: Path | str, entry: OpmlEntry) -> bool:
    """Append an entry to the OPML file. Idempotent on xmlUrl. Returns True if
    a new entry was added, False if it already existed."""
    entries = _load_or_empty(opml_path)
    for e in entries:
        if e.xml_url == entry.xml_url:
            return False
    entries.append(entry)
    write(entries, opml_path)
    return True


def remove_entry(opml_path: Path | str, xml_url: str) -> bool:
    """Remove an entry by xmlUrl. No-op if not present. Returns True if removed."""
    entries = _load_or_empty(opml_path)
    new = [e for e in entries if e.xml_url != xml_url]
    if len(new) == len(entries):
        return False
    write(new, opml_path)
    return True


def update_entry(
    opml_path: Path | str,
    xml_url: str,
    *,
    text: str | None = None,
    abbrev: str | None = None,
    color: str | None = None,
    html_url: str | None = None,
) -> bool:
    """Modify an entry in place. Pass None to leave a field unchanged; pass an
    empty string to clear abbrev/color/html_url. Returns True if updated."""
    entries = _load_or_empty(opml_path)
    changed = False
    for i, e in enumerate(entries):
        if e.xml_url != xml_url:
            continue
        new_title = text if text else e.title
        new_abbrev = e.abbrev if abbrev is None else (abbrev or None)
        new_color = e.color if color is None else (color or None)
        new_html = e.html_url if html_url is None else (html_url or None)
        entries[i] = OpmlEntry(
            title=new_title,
            xml_url=e.xml_url,
            html_url=new_html,
            abbrev=new_abbrev,
            color=new_color,
        )
        changed = True
        break
    if changed:
        write(entries, opml_path)
    return changed


def sync_to_db(opml_path: Path | str, storage) -> tuple[int, int]:
    """Reconcile OPML into the DB: ensure every OPML entry has a feed row whose
    display title / abbrev / color match the OPML. Returns (added, updated).
    Does NOT delete DB rows for feeds missing from OPML."""
    entries = _load_or_empty(opml_path)
    if not entries:
        return (0, 0)
    by_url = {f.url: f for f in storage.list_feeds()}
    added = 0
    updated = 0
    for e in entries:
        feed = by_url.get(e.xml_url)
        is_new = False
        if feed is None:
            storage.add_feed(url=e.xml_url, title=e.title, site_url=e.html_url)
            feed = next(
                (f for f in storage.list_feeds() if f.url == e.xml_url), None
            )
            added += 1
            is_new = True
            if feed is None:
                continue
        # Reconcile display title / abbrev / color (OPML wins).
        feed_changed = False
        if e.title and feed.name != e.title:
            storage.rename_feed(feed.id, e.title)
            feed_changed = True
        if (e.abbrev or None) != (feed.abbrev or None):
            storage.set_abbrev(feed.id, e.abbrev or None)
            feed_changed = True
        if (e.color or None) != (feed.color or None):
            storage.set_color(feed.id, e.color or None)
            feed_changed = True
        if feed_changed and not is_new:
            updated += 1
    return (added, updated)
