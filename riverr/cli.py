from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from riverr.core import opml as opml_mod
from riverr.core.config import get_paths
from riverr.core.feeds import add_by_url
from riverr.core.fetch import fetch_all
from riverr.core.storage import Storage


def _bootstrap_storage() -> Storage:
    """OPML is the source of truth. On every launch:
      - If ~/.config/riverr/feeds.opml is missing, seed it from the
        packaged seeds.opml.
      - Reconcile OPML → DB: add missing feeds; align display title /
        abbrev / color (OPML wins). Never delete DB rows.
    """
    paths = get_paths()
    storage = Storage(paths.db)
    if not paths.opml.exists():
        packaged = Path(__file__).resolve().parent.parent / "seeds.opml"
        if packaged.exists():
            paths.opml.write_text(packaged.read_text(encoding="utf-8"), encoding="utf-8")
    if paths.opml.exists():
        opml_mod.sync_to_db(paths.opml, storage)
    return storage


def cmd_v7(args: argparse.Namespace) -> int:
    from riverr.variants.v7_river_plus.app import V7App

    storage = _bootstrap_storage()
    V7App(storage=storage).run()
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    for f in _bootstrap_storage().list_feeds():
        print(f"  {f.id:3d}  {f.name:30s}  {f.url}")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    """Remove a feed by id, URL, or title. Updates OPML first, then DB."""
    paths = get_paths()
    storage = _bootstrap_storage()
    # Resolve to a URL so we can remove from OPML.
    url = _resolve_feed_url(storage, args.feed)
    if url is None:
        print(f"No feed matched: {args.feed}", file=sys.stderr)
        return 1
    opml_mod.remove_entry(paths.opml, url)
    storage.remove_feed(url)
    print(f"Removed: {args.feed}")
    return 0


def _resolve_feed_url(storage: Storage, feed: str) -> str | None:
    """Resolve a feed identifier (id, URL, title, or display title) to its URL."""
    if isinstance(feed, str) and feed.isdigit():
        f = storage.get_feed(int(feed))
        return f.url if f else None
    for f in storage.list_feeds():
        if f.url == feed or f.title == feed or (f.display_title and f.display_title == feed):
            return f.url
    return None


def cmd_items_reset(args: argparse.Namespace) -> int:
    """Unified wipe. --soft clears extracted bodies; --hard deletes item rows.
    Default is --soft. Keeps feed subscriptions, abbrev/color, and config."""
    storage = _bootstrap_storage()
    feed_filter = getattr(args, "feed", None)
    if feed_filter and not (isinstance(feed_filter, str) and feed_filter.isdigit()):
        feed_filter = _resolve_feed_url(storage, feed_filter) or feed_filter
    if getattr(args, "hard", False):
        n = storage.reset_items(feed_filter=feed_filter)
        print(f"Deleted {n} items. Run any variant and press Ctrl+R to re-fetch.")
    else:
        variant = getattr(args, "variant", None)
        n = storage.clear_extracted(feed_filter=feed_filter, format_filter=variant)
        print(f"Cleared extracted bodies for {n} items.")
    return 0


def cmd_reset_items(args: argparse.Namespace) -> int:
    print(
        "reset-items is deprecated; use 'riverr items reset --hard'.",
        file=sys.stderr,
    )
    args.hard = True
    return cmd_items_reset(args)


def cmd_image_test(args: argparse.Namespace) -> int:
    """Standalone image-rendering smoke test, no Textual app involved."""
    import base64
    import os
    import sys as _sys
    import httpx
    from riverr.core import images as imgmod

    print("Environment:")
    for k in ("TERM", "TERM_PROGRAM", "TERM_PROGRAM_VERSION",
              "KITTY_WINDOW_ID", "TMUX", "TMUX_PANE"):
        print(f"  {k:24s} = {os.environ.get(k, '<unset>')}")
    print(f"  supports_kitty_graphics  = {imgmod.supports_kitty_graphics()}")
    print(f"  supports_iterm_graphics  = {imgmod.supports_iterm_graphics()}")
    print(f"  supports_inline_images   = {imgmod.supports_inline_images()}")
    print()

    if os.environ.get("TMUX"):
        print("WARNING: TMUX is set. By default tmux strips Kitty graphics escapes.")
        print("         Either run this outside tmux, or add `set -g allow-passthrough on`")
        print("         to ~/.tmux.conf and `tmux kill-server`.")
        print()

    candidates = (
        [args.url] if args.url else [
            "https://www.gstatic.com/webp/gallery/1.png",
            "https://httpbin.org/image/png",
        ]
    )
    data = None
    for url in candidates:
        print(f"Fetching {url} ...")
        try:
            r = httpx.get(url, follow_redirects=True, timeout=15, headers={
                "User-Agent": "Mozilla/5.0 (compatible; riverr/0.1)",
                "Accept": "image/png,image/jpeg,image/*;q=0.8,*/*;q=0.5",
            })
            print(f"  HTTP {r.status_code}, {len(r.content)} bytes, ctype={r.headers.get('content-type')}")
            if r.status_code == 200 and r.content:
                data = r.content
                break
        except Exception as ex:
            print(f"  fetch failed: {ex}")
    if data is None:
        print("All candidates failed. Pass a known-good image URL: riverr image-test <url>")
        return 1

    if args.textual:
        return _image_test_textual(data)

    print()
    print("--- Raw Kitty graphics escape (bypasses Textual entirely) ---")
    b64 = base64.standard_b64encode(data).decode("ascii")
    chunks = [b64[i:i + 4096] for i in range(0, len(b64), 4096)]
    for i, chunk in enumerate(chunks):
        m = 1 if i < len(chunks) - 1 else 0
        if i == 0:
            _sys.stdout.write(f"\x1b_Ga=T,f=100,m={m};{chunk}\x1b\\")
        else:
            _sys.stdout.write(f"\x1b_Gm={m};{chunk}\x1b\\")
    _sys.stdout.write("\n")
    _sys.stdout.flush()
    print()
    print("If you see an image above this line, your terminal supports Kitty graphics.")
    print("If you see only garbled escape sequences, the terminal (or tmux) is not")
    print("passing them through.")
    print()
    print("For tmux: add to ~/.tmux.conf:")
    print("  set -g allow-passthrough on")
    print("then `tmux kill-server` and start a fresh session.")
    return 0


def _image_test_textual(data: bytes) -> int:
    """Mount one Image widget in a minimal Textual app. Isolates whether the
    bug is in textual-image / our protocol probe vs. in v7's mounting flow.
    """
    from riverr.core import images as imgmod
    from textual.app import App, ComposeResult
    from textual.containers import VerticalScroll
    from textual.widgets import Static

    print()
    print("--- Mounting an Image widget inside a minimal Textual app ---")
    print(f"  supports_kitty_graphics: {imgmod.supports_kitty_graphics()}")
    print("  (press q to exit the Textual app)")

    class ImageProbeApp(App):
        CSS = "Screen { layout: vertical; } #scroll { height: 1fr; }"
        BINDINGS = [("q", "quit", "Quit")]

        def compose(self) -> ComposeResult:
            yield Static("[b]If you can see an image below this line, "
                         "Textual + textual-image work in this terminal.[/]")
            with VerticalScroll(id="scroll"):
                widget = imgmod.make_image_widget(data)
                if widget is None:
                    yield Static("[red]make_image_widget returned None — "
                                 "the protocol probe or widget construction "
                                 "is broken.[/]")
                else:
                    yield widget
                yield Static("[dim]— end —[/]")

    ImageProbeApp().run()
    return 0


def cmd_smoke(args: argparse.Namespace) -> int:
    import os
    storage = _bootstrap_storage()
    feeds = storage.list_feeds()
    urls = [f.url for f in feeds]
    transport = None
    if os.environ.get("RIVERR_FIXTURES"):
        from riverr.core._fixtures import make_transport
        transport = make_transport()
    results = asyncio.run(fetch_all(urls, transport=transport))
    total_new = 0
    for f, res in zip(feeds, results):
        n = storage.upsert_items(f.id, res.items) if res.ok else 0
        total_new += n
        status = "OK" if res.ok else f"ERR ({res.error})"
        print(f"  {f.name:25s}  {status}  +{n} new  ({len(res.items)} items)")
    print(f"Total new items: {total_new}")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    paths = get_paths()
    storage = _bootstrap_storage()
    feed_id = asyncio.run(add_by_url(args.url, storage))
    feed = storage.get_feed(feed_id)
    if feed:
        # Write to OPML first (idempotent), then re-sync so DB matches.
        opml_mod.add_entry(
            paths.opml,
            opml_mod.OpmlEntry(
                title=feed.name, xml_url=feed.url, html_url=feed.site_url,
                abbrev=feed.abbrev, color=feed.color,
            ),
        )
        opml_mod.sync_to_db(paths.opml, storage)
        print(f"Added: {feed.name} ({feed.url})")
    return 0


def cmd_clear_cache(args: argparse.Namespace) -> int:
    print(
        "clear-cache is deprecated; use 'riverr items reset --soft'.",
        file=sys.stderr,
    )
    args.hard = False
    return cmd_items_reset(args)


def cmd_import(args: argparse.Namespace) -> int:
    paths = get_paths()
    storage = _bootstrap_storage()
    entries = opml_mod.parse(args.path)
    for e in entries:
        opml_mod.add_entry(paths.opml, e)
    added, _ = opml_mod.sync_to_db(paths.opml, storage)
    print(f"Imported {len(entries)} feeds ({added} new).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="riverr")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="enable debug logging for this run (writes to debug.log)",
    )
    sub = parser.add_subparsers(dest="command", required=False)

    p = sub.add_parser("v7", help="launch the reader (default if no subcommand)")
    p.set_defaults(func=cmd_v7)

    p = sub.add_parser("smoke", help="non-UI fetch test")
    p.set_defaults(func=cmd_smoke)

    p = sub.add_parser(
        "items", help="manage stored items (reset, etc.)"
    )
    items_sub = p.add_subparsers(dest="items_command", required=True)
    pr = items_sub.add_parser(
        "reset",
        help="wipe items: --soft clears extracted bodies (default), --hard deletes rows",
    )
    mode = pr.add_mutually_exclusive_group()
    mode.add_argument("--soft", dest="hard", action="store_false",
                      help="clear extracted bodies only (default)")
    mode.add_argument("--hard", dest="hard", action="store_true",
                      help="delete item rows entirely (forces re-fetch)")
    pr.set_defaults(hard=False)
    pr.add_argument("--feed", default=None,
                    help="restrict to a feed (id, URL, or title)")
    pr.add_argument("--variant", choices=("markdown", "html"), default=None,
                    help="(--soft only) limit to items whose body_format matches")
    pr.set_defaults(func=cmd_items_reset)

    p = sub.add_parser("reset-items",
                       help="(deprecated) use 'items reset --hard'")
    p.add_argument("--feed", default=None, help="restrict to a feed (id, URL, or title)")
    p.set_defaults(func=cmd_reset_items)

    p = sub.add_parser("remove", help="remove a feed (by id, URL, or title)")
    p.add_argument("feed")
    p.set_defaults(func=cmd_remove)

    p = sub.add_parser("list", help="list subscribed feeds")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("image-test",
                       help="standalone Kitty-graphics test (no Textual)")
    p.add_argument("url", nargs="?", default=None,
                   help="image URL (default: a small known-good PNG)")
    p.add_argument("--textual", action="store_true",
                   help="also mount the image inside a minimal Textual app")
    p.set_defaults(func=cmd_image_test)

    p = sub.add_parser("add", help="add a feed by URL")
    p.add_argument("url")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("import", help="import an OPML file")
    p.add_argument("path")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser(
        "clear-cache",
        help="(deprecated) use 'items reset --soft'",
    )
    p.add_argument(
        "--feed", help="limit to a single feed (id, URL, or title)",
        default=None,
    )
    p.add_argument(
        "--variant", choices=("markdown", "html"),
        help="limit to items whose stored body_format matches",
        default=None,
    )
    p.set_defaults(func=cmd_clear_cache)

    args = parser.parse_args(argv)
    from .core import logging as fr_logging
    fr_logging.configure(level="debug" if getattr(args, "debug", False) else None)
    # Default to launching the reader if no subcommand given.
    if not getattr(args, "command", None):
        return cmd_v7(args)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
