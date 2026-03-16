"""markdown_tool — Convert, strip, and inspect Markdown text."""
from __future__ import annotations
import re, logging

logger = logging.getLogger(__name__)


def markdown_tool(action: str, text: str) -> str:
    """
    Work with Markdown text.

    action : to_html | to_text | headings | links | code_blocks | word_count | outline
    text   : The Markdown string to process.

    Actions:
        to_html     : Convert Markdown to basic HTML (no external libraries needed).
        to_text     : Strip all Markdown syntax and return plain text.
        headings    : List all headings with their levels.
        links       : Extract all [label](url) links.
        code_blocks : Extract all fenced code blocks.
        word_count  : Word count after stripping Markdown.
        outline     : Indented heading outline.
    """
    if not action or not isinstance(action, str):
        return "Error: 'action' is required."
    if not isinstance(text, str):
        text = str(text)

    action = action.strip().lower()

    if action == "to_html":
        return _to_html(text)

    if action == "to_text":
        return _strip_markdown(text)

    if action == "headings":
        headings = re.findall(r"^(#{1,6})\s+(.+)$", text, re.MULTILINE)
        if not headings:
            return "No headings found."
        return "\n".join(f"H{len(h)}  {t.strip()}" for h, t in headings)

    if action == "links":
        links = re.findall(r"\[([^\]]+)\]\(([^)]+)\)", text)
        if not links:
            return "No links found."
        return "\n".join(f"  [{label}] → {url}" for label, url in links)

    if action == "code_blocks":
        blocks = re.findall(r"```(\w*)\n(.*?)```", text, re.DOTALL)
        if not blocks:
            return "No fenced code blocks found."
        out = []
        for i, (lang, code) in enumerate(blocks, 1):
            lang_label = lang.strip() or "plain"
            out.append(f"--- Block {i} ({lang_label}) ---\n{code.strip()}")
        return "\n\n".join(out)

    if action == "word_count":
        plain = _strip_markdown(text)
        words = len(plain.split())
        return f"Words: {words}"

    if action == "outline":
        headings = re.findall(r"^(#{1,6})\s+(.+)$", text, re.MULTILINE)
        if not headings:
            return "No headings found."
        lines = []
        for h, t in headings:
            level = len(h)
            indent = "  " * (level - 1)
            lines.append(f"{indent}{'•' if level > 1 else '▶'} {t.strip()}")
        return "\n".join(lines)

    return f"Unknown action '{action}'. Use: to_html, to_text, headings, links, code_blocks, word_count, outline."


# ── conversion helpers ────────────────────────────────────────────────────────

def _to_html(md: str) -> str:
    """Lightweight Markdown → HTML (covers headings, bold, italic, links, code, lists, HR, paragraphs)."""
    lines = md.split("\n")
    out   = []
    in_code = False
    code_lang = ""

    for line in lines:
        # Fenced code blocks
        m_fence = re.match(r"^```(\w*)", line)
        if m_fence and not in_code:
            in_code   = True
            code_lang = m_fence.group(1)
            lang_class = f' class="language-{code_lang}"' if code_lang else ""
            out.append(f"<pre><code{lang_class}>")
            continue
        if line.strip() == "```" and in_code:
            in_code = False
            out.append("</code></pre>")
            continue
        if in_code:
            out.append(_escape_html(line))
            continue

        # Headings
        m_h = re.match(r"^(#{1,6})\s+(.*)", line)
        if m_h:
            lvl = len(m_h.group(1))
            out.append(f"<h{lvl}>{_inline(m_h.group(2))}</h{lvl}>")
            continue

        # HR
        if re.match(r"^[-*_]{3,}\s*$", line):
            out.append("<hr>")
            continue

        # Unordered list item
        m_li = re.match(r"^[-*+]\s+(.*)", line)
        if m_li:
            out.append(f"<li>{_inline(m_li.group(1))}</li>")
            continue

        # Ordered list item
        m_ol = re.match(r"^\d+\.\s+(.*)", line)
        if m_ol:
            out.append(f"<li>{_inline(m_ol.group(1))}</li>")
            continue

        # Blank line
        if not line.strip():
            out.append("")
            continue

        # Paragraph line
        out.append(f"<p>{_inline(line)}</p>")

    return "\n".join(out)


def _inline(text: str) -> str:
    """Apply inline Markdown rules (bold, italic, code, links, images)."""
    text = _escape_html(text)
    # Images before links
    text = re.sub(r"!\[([^\]]*)\]\(([^)]*)\)", r'<img src="\2" alt="\1">', text)
    # Links
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    # Inline code
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    # Bold + italic
    text = re.sub(r"\*{3}(.+?)\*{3}", r"<strong><em>\1</em></strong>", text)
    text = re.sub(r"\*{2}(.+?)\*{2}", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*",       r"<em>\1</em>",         text)
    text = re.sub(r"_{2}(.+?)_{2}",   r"<strong>\1</strong>", text)
    text = re.sub(r"_(.+?)_",         r"<em>\1</em>",         text)
    # Strikethrough
    text = re.sub(r"~~(.+?)~~",       r"<del>\1</del>",       text)
    return text


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _strip_markdown(md: str) -> str:
    text = re.sub(r"```.*?```", "", md, flags=re.DOTALL)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"^\s*#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"[*_]{1,3}(.+?)[*_]{1,3}", r"\1", text)
    text = re.sub(r"~~(.+?)~~", r"\1", text)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
