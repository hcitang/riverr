# riverr

**River RSS Reader.** A terminal RSS reader that gives you a single chronological river of every item from every feed — and reads you the *article*, not the stub.

> 🤖 **Built collaboratively with [Claude Code](https://claude.com/claude-code).** Almost every line in this repo was written by Claude under direction; I steered the design, called the shots, reviewed and rejected ideas, and pushed the iteration through seven UI prototypes (the first six are gone now — only the survivor ships). The architecture, the refactors, the bug hunts, the tests — Claude did the typing. Treat the code accordingly: it's reasonable, it works on my machine, but it hasn't had the kind of human-eyes-everywhere review that a serious project deserves.
>
> Status: vibes-only. Released because the *process* is interesting (terminal RSS reader by way of agentic pair-programming), not because it's actively maintained. No warranty, no roadmap, no obligation to fix anything. Pull requests welcome but may be ignored. Consider this a snapshot of "this works on my machine on a Saturday in 2026."

## What it looks like

```
river+ ▸ All Feeds                            128 unread · last refresh 17:08
▼  CBC    Deaths of people experiencing homelessness on rise for 5th year   45m
   ┌──────────────────────────────────────────────────────────────────┐
   │ Deaths of people experiencing homelessness on rise for 5th year  │
   │ [source: extracted markdown · trafilatura]                       │
   │ https://www.cbc.ca/news/canada/british-columbia/...              │
   │                                                                  │
   │ B.C.'s chief coroner says the number of homeless people who      │
   │ died last year rose for the fifth year in a row, with toxic drug │
   │ supply still the dominant factor...                              │
   └──────────────────────────────────────────────────────────────────┘
   CNA    BOJ's Himino calls for holistic approach on monetary system  3h
   HN     The CTF scene is dead                                        4h
●  DF     ★ The Talk Show Episode 412                                  5h
   CBC    Heat dome blamed for Pacific salmon collapse                 9h
●  CHI    Postdoctoral Research Scientist at CMU                       1d
 ^r Refresh   R Mark below read   y Yank   o Open URL   q Quit   v Images
```

## Quick install

```bash
git clone https://github.com/hcitang/riverr ~/Repos/riverr
cd ~/Repos/riverr
pip install -e .
```

Python 3.12+. macOS (only place it's been tested). Both `riverr` and `rr` end up on your PATH; if you have Mozilla's [rr debugger](https://rr-project.org/) installed, use the long form to avoid the collision.

## First run

```bash
rr
```

That's it — no subcommand needed. It bootstraps from a packaged seeds OPML (HN, CBC, CNA, Daring Fireball) into `~/.config/riverr/feeds.opml`. Press `^r` to fetch, `Enter` to expand an item, `q` to quit.

## The idea

Most news RSS feeds today ship a title, a paragraph of preview text, and a "read more" link. That's useless if you want to actually read. **riverr fetches the linked article** and runs it through trafilatura → markdown (with a readability-lxml fallback), so what you see in the reader is the article body itself. Caches the extracted bodies in SQLite so it only does the fetch once.

The other organizing idea is the **river**: one chronological stream of every unread item from every feed, each tagged with a colored 3-letter abbreviation. No folders, no piles — just the stream, with `<`/`>` to switch between "all feeds", "this one feed", and "starred only".

## Keys

| Key | Action |
|---|---|
| `j` / `↓` , `k` / `↑` | next / prev item |
| `space` / `J` / `^j` | page down (cursor follows) |
| `K` / `^k` / `^space` / `b` | page up |
| `Enter` | expand / collapse focused article |
| `space` in expanded article | scroll body; collapse when at end |
| `j` / `k` in expanded article | move to next/prev item; `j` auto-expands the next |
| `Tab` / `Shift-Tab` | cycle links/images inside the focused article |
| `y` | yank focused link URL to clipboard (OSC 52 — works inside tmux with `set -g allow-passthrough on`) |
| `o` | open focused link in default browser |
| `s` | star / unstar focused item |
| `u` | toggle read/unread on focused item |
| `R` | mark every item at-or-below the cursor as read (respects current view) |
| `<` / `>` | switch view (All Feeds → per-feed cycle → Starred) |
| `f` | feed-picker overlay |
| `e` | edit focused feed (display title, 3-char abbreviation, `#RRGGBB` color) |
| `/` | filter visible list |
| `?` | global full-text search across all items |
| `v` | toggle inline images |
| `^r` | refresh feeds (non-blocking) |
| `q` | quit |
| `^p` | command palette (built-in to Textual) |

Override any binding by writing `~/.config/riverr/keys.toml`:

```toml
[keys]
quit = "Q"
page_down = "ctrl+d"
```

## Configuration

Two files in `~/.config/riverr/`:

- **`feeds.opml`** — subscriptions. Source of truth. Add/remove/edit from the CLI or v7's modal, or hand-edit this file. Compatible with any OPML reader; abbrev/color stored as `fr:abbrev` / `fr:color` extension attributes.
- **`keys.toml`** — keybinding overrides (optional). The defaults in `riverr/core/keys.py` cover everything.

Runtime preferences live in `~/.config/riverr/settings.toml`:

```toml
[display]
images_enabled = true     # toggled by `v` in v7
cell_px_height = 20       # for image scaling
clipboard = "osc52"       # or "pbcopy"

[behavior]
expanded_j = "open_next"      # or "collapse_only"
expanded_k = "close_and_prev" # or "collapse_only"

[logging]
level = "off"             # off | debug | info | warning
```

State (read flags, extracted article bodies, FTS index, stars) lives in `~/.local/share/riverr/state.db` (SQLite, WAL mode). Safe to delete; subscriptions come back from OPML.

## CLI commands

```bash
rr                                    # launch the reader (same as `rr v7`)

rr list                               # list subscribed feeds with ids
rr add <url>                          # add a feed (auto-discovers title)
rr remove <id|url|title>              # remove a feed and its items
rr import <opml-path>                 # import an OPML file

rr items reset [--soft|--hard]        # --soft: clear extracted bodies; --hard: delete item rows
                  [--feed X]
rr smoke                              # one-shot fetch of all feeds, prints counts
rr image-test [--textual] [URL]       # standalone Kitty graphics smoke test
```

## Inline images

riverr renders article images inline using the [Kitty graphics protocol](https://sw.kovidgoyal.net/kitty/graphics-protocol/). Tested in Ghostty. iTerm2 and Kitty should work; other terminals fall back to `[image: alt-text]` placeholders.

Inside tmux, graphics escapes are stripped by default. Add `set -g allow-passthrough on` to your tmux config to enable them. Same applies to `y`/yank (OSC 52 clipboard) — add `set -g set-clipboard on`.

If you're in Ghostty and images still don't show, run `rr image-test` outside tmux — the raw escape codes bypass our code entirely, so if that works but the reader doesn't, the bug is ours.

## Cloudflare-protected feeds

Some feeds (looking at you, `listserv.acm.org`) sit behind Cloudflare and reject `httpx` requests with a 403. riverr detects the Cloudflare server header and retries via [cloudscraper](https://github.com/VeNoMouS/cloudscraper), which passes the basic JS challenge. Also applies to article-extraction fetches. If your feed still 403s, it's likely behind Cloudflare Turnstile, which is harder; you can try setting up [curl_cffi](https://github.com/yifeikong/curl_cffi) as a manual workaround.

## How it's built

- **Python 3.12** + [Textual](https://textual.textualize.io/) for the TUI
- **SQLite** with FTS5 for storage + full-text search; WAL mode so multiple `riverr` processes don't corrupt the DB
- **feedparser** / **httpx** for fetching
- **trafilatura** + **readability-lxml** + **markdownify** for article extraction → markdown
- **markdown-it-py** for markdown → AST → Textual widgets
- **Pillow** for image dimension probing (Kitty escapes need to know the cell-height)
- All test fixtures stored locally; tests never hit the network

```
riverr/
  core/        the public surface: storage, opml, feeds, fetch, extract, render,
               keys, images, links, search, app_base, logging, settings, models
  variants/
    v7_river_plus/   the reader (app.py + rows / body / edit_modal / style / behavior)
tests/         unit + Textual `App.run_test()` pilot tours (~120 tests, all offline)
```

The reader is the 7th iteration. The first six prototypes (NNW classic 3-pane, miller columns, pine-stacked screens, inline-expand tree, river of news, vim-modal command bar) were the design exploration that got here; v7 borrows something useful from almost every one of them.

## Things that don't work / aren't there

- No multi-machine sync (and no plan to add one)
- No folders, no tags beyond starring
- iTerm2 / sixel inline images are detected but not actively maintained
- HN comments view is intentionally absent — riverr is for reading articles
- Linux/Windows: unknown — should work but untested
- No daemon mode, no scheduled background refresh; refresh is always user-initiated

## Why does this exist

Mostly because I wanted a terminal RSS reader that read articles instead of stubs, and because I wanted to know if the iteration approach (build six wildly different UIs first, then pick the one that worked) would actually beat starting from a single design. Turned out v7 borrowed something useful from almost every prototype.

Also: half-decent excuse to learn Textual. If you write your own terminal app, it's worth a look — the reflow + keymap + async story is well thought through.

## Credits

- **Implementation**: [Claude Code](https://claude.com/claude-code) (Anthropic's CLI coding agent), Opus 4.7 model. I drove; Claude wrote.
- **Iteration approach**: build six wildly different UI prototypes in parallel, then converge on what actually felt good. Hat-tip to that workflow — it produced a better v7 than starting from one design would have.
- **HN front-page RSS** via [hnrss.org](https://hnrss.org).
- **Article extraction** via [trafilatura](https://github.com/adbar/trafilatura) and [readability-lxml](https://github.com/buriy/python-readability).
- **TUI** via [Textual](https://textual.textualize.io/).

## License

MIT. See `LICENSE`.
