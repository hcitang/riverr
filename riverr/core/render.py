from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Optional

from rich.text import Text


# --- AST nodes ---

@dataclass
class Node:
    pass


@dataclass
class Text_(Node):
    text: str


@dataclass
class Bold(Node):
    children: list["Node"] = field(default_factory=list)


@dataclass
class Italic(Node):
    children: list["Node"] = field(default_factory=list)


@dataclass
class Underline(Node):
    children: list["Node"] = field(default_factory=list)


@dataclass
class Code(Node):
    text: str


@dataclass
class Link(Node):
    href: str
    children: list["Node"] = field(default_factory=list)


@dataclass
class Image(Node):
    src: str
    alt: str = ""


@dataclass
class Heading(Node):
    level: int
    children: list["Node"] = field(default_factory=list)


@dataclass
class Paragraph(Node):
    children: list["Node"] = field(default_factory=list)


@dataclass
class CodeBlock(Node):
    text: str
    language: str = ""


@dataclass
class Blockquote(Node):
    children: list["Node"] = field(default_factory=list)


@dataclass
class ListItem(Node):
    children: list["Node"] = field(default_factory=list)


@dataclass
class List_(Node):
    ordered: bool = False
    items: list[ListItem] = field(default_factory=list)


@dataclass
class Document(Node):
    children: list[Node] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    images: list[tuple[str, str]] = field(default_factory=list)


# --- HTML → AST parser ---

BLOCK_TAGS = {"p", "div", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6",
              "ul", "ol", "li", "blockquote", "pre", "br", "hr"}
INLINE_TAGS = {"b", "strong", "i", "em", "u", "a", "code", "img", "span"}


class _HtmlToAst(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.doc = Document()
        self.stack: list[Node] = [self.doc]
        self._pre_depth = 0
        self._pre_buf: list[str] = []

    def _push_container(self, node: Node) -> None:
        parent = self.stack[-1]
        if isinstance(parent, Document):
            parent.children.append(node)
        elif isinstance(parent, (Paragraph, Heading, Blockquote, ListItem,
                                 Bold, Italic, Underline, Link)):
            parent.children.append(node)
        elif isinstance(parent, List_):
            if isinstance(node, ListItem):
                parent.items.append(node)
        self.stack.append(node)

    def _append_inline(self, node: Node) -> None:
        parent = self.stack[-1]
        if isinstance(parent, Document):
            p = Paragraph()
            self.doc.children.append(p)
            self.stack.append(p)
            parent = p
        if hasattr(parent, "children"):
            parent.children.append(node)  # type: ignore[attr-defined]

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "p":
            self._push_container(Paragraph())
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._push_container(Heading(level=int(tag[1])))
        elif tag == "ul":
            self._push_container(List_(ordered=False))
        elif tag == "ol":
            self._push_container(List_(ordered=True))
        elif tag == "li":
            self._push_container(ListItem())
        elif tag == "blockquote":
            self._push_container(Blockquote())
        elif tag == "pre":
            self._pre_depth += 1
            self._pre_buf = []
        elif tag in {"b", "strong"}:
            self._push_container(Bold())
        elif tag in {"i", "em"}:
            self._push_container(Italic())
        elif tag == "u":
            self._push_container(Underline())
        elif tag == "a":
            href = a.get("href", "")
            link = Link(href=href)
            self._append_inline(link)
            self.stack.append(link)
            if href:
                self.doc.links.append(href)
        elif tag == "code":
            if self._pre_depth:
                return
            # leave as inline; handled via data
            self._push_container(Code(text=""))
        elif tag == "img":
            src = a.get("src", "")
            alt = a.get("alt", "")
            self._append_inline(Image(src=src, alt=alt))
            if src:
                self.doc.images.append((src, alt))
        elif tag == "br":
            self._append_inline(Text_("\n"))

    def handle_endtag(self, tag):
        if tag == "pre":
            text = "".join(self._pre_buf)
            self.doc.children.append(CodeBlock(text=text.strip("\n")))
            self._pre_buf = []
            self._pre_depth = max(0, self._pre_depth - 1)
            return
        close_set = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li",
                     "blockquote", "b", "strong", "i", "em", "u", "a", "code"}
        if tag in close_set:
            # pop until matching node type
            target = {
                "p": Paragraph, "h1": Heading, "h2": Heading, "h3": Heading,
                "h4": Heading, "h5": Heading, "h6": Heading,
                "ul": List_, "ol": List_, "li": ListItem,
                "blockquote": Blockquote, "b": Bold, "strong": Bold,
                "i": Italic, "em": Italic, "u": Underline, "a": Link,
                "code": Code,
            }[tag]
            for i in range(len(self.stack) - 1, 0, -1):
                if isinstance(self.stack[i], target):
                    del self.stack[i:]
                    break

    def handle_data(self, data):
        if self._pre_depth:
            self._pre_buf.append(data)
            return
        if not data:
            return
        parent = self.stack[-1]
        if isinstance(parent, Code):
            parent.text += data
            return
        # collapse whitespace runs but keep meaningful spaces
        text = data
        if isinstance(parent, Document):
            if not text.strip():
                return
            p = Paragraph(children=[Text_(text)])
            self.doc.children.append(p)
            return
        if hasattr(parent, "children"):
            parent.children.append(Text_(text))  # type: ignore[attr-defined]


def _html_to_ast(html: str) -> Document:
    """Private: only used for embedded `html_block` tokens inside markdown.
    Public render path is markdown-only."""
    p = _HtmlToAst()
    p.feed(html or "")
    return p.doc


# --- Markdown → AST ---

def markdown_to_ast(md_text: str) -> Document:
    """Parse Markdown via markdown-it-py and produce our Document AST."""
    from markdown_it import MarkdownIt

    md = MarkdownIt("commonmark", {"html": True, "linkify": True}).enable("table")
    tokens = md.parse(md_text or "")
    doc = Document()
    _md_consume(tokens, doc)
    return doc


def _md_consume(tokens, doc: Document) -> None:
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        t = tok.type
        if t == "heading_open":
            level = int(tok.tag[1])
            j = _find_close(tokens, i, "heading_close")
            children = _md_inline(tokens[i + 1:j], doc)
            doc.children.append(Heading(level=level, children=children))
            i = j + 1
        elif t == "paragraph_open":
            j = _find_close(tokens, i, "paragraph_close")
            children = _md_inline(tokens[i + 1:j], doc)
            doc.children.append(Paragraph(children=children))
            i = j + 1
        elif t == "blockquote_open":
            j = _find_matching_close(tokens, i, "blockquote_open", "blockquote_close")
            inner = Document()
            _md_consume(tokens[i + 1:j], inner)
            bq = Blockquote(children=inner.children)
            doc.children.append(bq)
            doc.links.extend(inner.links)
            doc.images.extend(inner.images)
            i = j + 1
        elif t in ("bullet_list_open", "ordered_list_open"):
            ordered = t == "ordered_list_open"
            close = "bullet_list_close" if not ordered else "ordered_list_close"
            j = _find_matching_close(tokens, i, t, close)
            lst = List_(ordered=ordered)
            k = i + 1
            while k < j:
                if tokens[k].type == "list_item_open":
                    item_close = _find_matching_close(
                        tokens, k, "list_item_open", "list_item_close"
                    )
                    li_doc = Document()
                    _md_consume(tokens[k + 1:item_close], li_doc)
                    li = ListItem(children=li_doc.children)
                    lst.items.append(li)
                    doc.links.extend(li_doc.links)
                    doc.images.extend(li_doc.images)
                    k = item_close + 1
                else:
                    k += 1
            doc.children.append(lst)
            i = j + 1
        elif t in ("fence", "code_block"):
            lang = tok.info.strip() if tok.info else ""
            doc.children.append(CodeBlock(text=(tok.content or "").rstrip("\n"), language=lang))
            i += 1
        elif t == "hr":
            # Render as an empty paragraph divider.
            doc.children.append(Paragraph(children=[Text_("───")]))
            i += 1
        elif t == "html_block":
            # Convert nested HTML through the HTML parser, append its blocks.
            sub = _html_to_ast(tok.content or "")
            doc.children.extend(sub.children)
            doc.links.extend(sub.links)
            doc.images.extend(sub.images)
            i += 1
        elif t == "inline":
            children = _md_inline([tok], doc)
            if children:
                doc.children.append(Paragraph(children=children))
            i += 1
        else:
            i += 1


def _find_close(tokens, start, close_type):
    for k in range(start + 1, len(tokens)):
        if tokens[k].type == close_type:
            return k
    return len(tokens)


def _find_matching_close(tokens, start, open_type, close_type):
    depth = 0
    for k in range(start, len(tokens)):
        if tokens[k].type == open_type:
            depth += 1
        elif tokens[k].type == close_type:
            depth -= 1
            if depth == 0:
                return k
    return len(tokens)


def _md_inline(tokens, doc: Document) -> list[Node]:
    """Convert a sequence of inline (block-level) tokens whose children
    are markdown-it inline tokens to a flat list of Node children."""
    out: list[Node] = []
    for tok in tokens:
        if tok.type != "inline":
            continue
        out.extend(_md_inline_children(tok.children or [], doc))
    return out


def _md_inline_children(children, doc: Document) -> list[Node]:
    out: list[Node] = []
    stack: list[list[Node]] = [out]
    open_kinds: list[str] = []
    for tok in children:
        t = tok.type
        if t == "text":
            stack[-1].append(Text_(tok.content))
        elif t == "softbreak":
            stack[-1].append(Text_(" "))
        elif t == "hardbreak":
            stack[-1].append(Text_("\n"))
        elif t == "code_inline":
            stack[-1].append(Code(text=tok.content))
        elif t == "image":
            src = ""
            alt = ""
            for k, v in tok.attrs.items() if tok.attrs else []:
                if k == "src":
                    src = v
                elif k == "alt":
                    alt = v
            if not alt and tok.children:
                alt = "".join(
                    c.content for c in tok.children if c.type == "text"
                )
            stack[-1].append(Image(src=src, alt=alt))
            if src:
                doc.images.append((src, alt))
        elif t == "link_open":
            href = ""
            for k, v in tok.attrs.items() if tok.attrs else []:
                if k == "href":
                    href = v
            link = Link(href=href)
            stack[-1].append(link)
            stack.append(link.children)
            open_kinds.append("link")
            if href:
                doc.links.append(href)
        elif t == "link_close":
            if open_kinds and open_kinds[-1] == "link":
                stack.pop()
                open_kinds.pop()
        elif t == "strong_open" or t == "b_open":
            node = Bold()
            stack[-1].append(node)
            stack.append(node.children)
            open_kinds.append("strong")
        elif t == "strong_close" or t == "b_close":
            if open_kinds and open_kinds[-1] == "strong":
                stack.pop()
                open_kinds.pop()
        elif t == "em_open" or t == "i_open":
            node = Italic()
            stack[-1].append(node)
            stack.append(node.children)
            open_kinds.append("em")
        elif t == "em_close" or t == "i_close":
            if open_kinds and open_kinds[-1] == "em":
                stack.pop()
                open_kinds.pop()
        elif t == "s_open":
            node = Italic()
            stack[-1].append(node)
            stack.append(node.children)
            open_kinds.append("s")
        elif t == "s_close":
            if open_kinds and open_kinds[-1] == "s":
                stack.pop()
                open_kinds.pop()
        elif t == "html_inline":
            # Treat raw HTML inline as plain text to avoid losing content.
            stack[-1].append(Text_(tok.content or ""))
        # other inline types fall through
    return out


def render_markdown(md_text: str) -> Document:
    """Public helper for markdown input."""
    return markdown_to_ast(md_text)


def item_body_to_ast(item) -> Document:
    """Render path is markdown-only. Storage migration converts any legacy
    HTML rows to markdown at Storage open time."""
    body = item.extracted_body or item.body or ""
    return markdown_to_ast(body)


# --- AST → Rich Text ---

H_COLORS = {1: "bold bright_white", 2: "bold cyan", 3: "bold green",
            4: "bold yellow", 5: "bold magenta", 6: "bold blue"}


def _render_inline(node: Node, out: Text, link_targets: list[str],
                   image_targets: list[tuple[str, str]] | None = None) -> None:
    if isinstance(node, Text_):
        out.append(node.text)
    elif isinstance(node, Bold):
        sub = Text()
        for c in node.children:
            _render_inline(c, sub, link_targets, image_targets)
        sub.stylize("bold bright_white")
        out.append_text(sub)
    elif isinstance(node, Italic):
        sub = Text()
        for c in node.children:
            _render_inline(c, sub, link_targets, image_targets)
        sub.stylize("italic cyan")
        out.append_text(sub)
    elif isinstance(node, Underline):
        sub = Text()
        for c in node.children:
            _render_inline(c, sub, link_targets, image_targets)
        sub.stylize("underline bright_yellow")
        out.append_text(sub)
    elif isinstance(node, Code):
        out.append(node.text, style="bold bright_white on grey15")
    elif isinstance(node, Link):
        idx = len(link_targets) + 1
        link_targets.append(node.href)
        sub = Text()
        for c in node.children:
            _render_inline(c, sub, link_targets, image_targets)
        if not sub.plain:
            sub.append(node.href)
        sub.stylize("underline blue")
        out.append_text(sub)
        out.append(f"[{idx}]", style="dim")
    elif isinstance(node, Image):
        idx = len(link_targets) + 1
        link_targets.append(node.src)
        if image_targets is not None:
            image_targets.append((node.src, node.alt))
        out.append(f"[image: {node.alt or node.src}]", style="italic magenta")
        out.append(f"[{idx}]", style="dim")


def render_to_text(
    doc: Document,
    collect_images: bool = False,
) -> tuple[Text, list[str]] | tuple[Text, list[str], list[tuple[str, str]]]:
    out = Text()
    link_targets: list[str] = []
    image_targets: list[tuple[str, str]] = []
    for node in doc.children:
        _render_block(node, out, link_targets, depth=0, image_targets=image_targets)
    if collect_images:
        return out, link_targets, image_targets
    return out, link_targets


def _render_block(node: Node, out: Text, link_targets: list[str], depth: int,
                  image_targets: list[tuple[str, str]] | None = None) -> None:
    if isinstance(node, Heading):
        style = H_COLORS.get(node.level, "bold")
        if node.level == 1:
            style += " underline"
        sub = Text()
        for c in node.children:
            _render_inline(c, sub, link_targets, image_targets)
        sub.stylize(style)
        out.append("\n")
        out.append_text(sub)
        out.append("\n\n")
    elif isinstance(node, Paragraph):
        sub = Text()
        for c in node.children:
            _render_inline(c, sub, link_targets, image_targets)
        if sub.plain.strip():
            out.append(sub)
            out.append("\n\n")
    elif isinstance(node, CodeBlock):
        out.append(node.text + "\n", style="bright_white on grey11")
        out.append("\n")
    elif isinstance(node, Blockquote):
        for c in node.children:
            sub_text = Text()
            if isinstance(c, Paragraph):
                for cc in c.children:
                    _render_inline(cc, sub_text, link_targets, image_targets)
            else:
                _render_inline(c, sub_text, link_targets, image_targets)
            for line in sub_text.plain.splitlines() or [""]:
                out.append("  │ ", style="dim cyan")
                out.append(line + "\n", style="italic cyan")
        out.append("\n")
    elif isinstance(node, List_):
        for i, item in enumerate(node.items, 1):
            bullet = f"{i}. " if node.ordered else "• "
            out.append("  " * depth)
            out.append(bullet, style="bold yellow")
            sub = Text()
            for c in item.children:
                if isinstance(c, (Paragraph, List_, Heading, Blockquote, CodeBlock)):
                    _render_block(c, sub, link_targets, depth + 1, image_targets)
                else:
                    _render_inline(c, sub, link_targets, image_targets)
            out.append(sub)
            if not sub.plain.endswith("\n"):
                out.append("\n")
        out.append("\n")
    else:
        _render_inline(node, out, link_targets, image_targets)
