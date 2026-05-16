from riverr.core.render import (
    Blockquote, CodeBlock, Document, Heading, Image, Link, List_, ListItem,
    Paragraph, markdown_to_ast, render_to_text,
)


def test_heading_ast():
    doc = markdown_to_ast("# Title\n\nBody\n")
    assert any(isinstance(c, Heading) and c.level == 1 for c in doc.children)
    assert any(isinstance(c, Paragraph) for c in doc.children)


def test_list_ast():
    doc = markdown_to_ast("- one\n- two\n")
    lists = [c for c in doc.children if isinstance(c, List_)]
    assert len(lists) == 1
    assert len(lists[0].items) == 2


def test_link_ast_collected():
    doc = markdown_to_ast("see [here](https://example.com)\n")
    assert "https://example.com" in doc.links


def test_image_ast_collected():
    doc = markdown_to_ast("![alt](https://example.com/a.png)\n")
    assert ("https://example.com/a.png", "alt") in doc.images


def test_blockquote_ast():
    doc = markdown_to_ast("> Quoted\n")
    assert any(isinstance(c, Blockquote) for c in doc.children)


def test_codeblock_ast():
    doc = markdown_to_ast("```\nx = 1\n```\n")
    assert any(isinstance(c, CodeBlock) and "x = 1" in c.text for c in doc.children)


def test_render_to_text_smoke():
    doc = markdown_to_ast(
        "# Hello\n\n"
        "This is **bold** and *italic* and [a link](https://x.test).\n\n"
        "- one\n- two\n\n"
        "> quote\n\n"
        "```\ncode\n```\n"
    )
    text, links = render_to_text(doc)
    s = text.plain
    assert "Hello" in s
    assert "bold" in s
    assert "italic" in s
    assert "a link" in s
    assert "one" in s and "two" in s
    assert "quote" in s
    assert "code" in s
    assert "https://x.test" in links


def test_heading_style_applied():
    doc = markdown_to_ast("# Top\n")
    text, _ = render_to_text(doc)
    styles = " ".join(str(s.style) for s in text.spans)
    assert "bold" in styles.lower()
    assert "underline" in styles.lower()


def test_paragraphs_separated_by_blank_line():
    doc = markdown_to_ast("First paragraph.\n\nSecond paragraph.\n")
    text, _ = render_to_text(doc)
    lines = text.plain.split("\n")
    p1 = next(i for i, ln in enumerate(lines) if "First" in ln)
    p2 = next(i for i, ln in enumerate(lines) if "Second" in ln)
    assert p2 > p1
    assert any(lines[i].strip() == "" for i in range(p1 + 1, p2))


def test_markdown_image_ast_emitted():
    """Markdown image syntax `![alt](url)` must produce an Image AST node."""
    from riverr.core.render import markdown_to_ast, Image as ImageNode

    md = "Before.\n\n![pic](https://example.com/x.png)\n\nAfter.\n"
    doc = markdown_to_ast(md)
    found = []
    def walk(n):
        if isinstance(n, ImageNode):
            found.append((n.src, n.alt))
        for attr in ("children", "items"):
            for c in getattr(n, attr, []) or []:
                walk(c)
    walk(doc)
    assert ("https://example.com/x.png", "pic") in found
    assert "https://example.com/x.png" in [s for s, _ in doc.images]


def test_markdown_image_only_paragraph():
    """An image-only paragraph still produces an Image node."""
    from riverr.core.render import markdown_to_ast, Image as ImageNode, Paragraph

    doc = markdown_to_ast("![](https://example.com/y.png)\n")
    found = []
    def walk(n):
        if isinstance(n, ImageNode):
            found.append(n.src)
        for attr in ("children", "items"):
            for c in getattr(n, attr, []) or []:
                walk(c)
    walk(doc)
    assert "https://example.com/y.png" in found
