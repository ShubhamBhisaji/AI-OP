"""pdf_tool — Generate PDF documents from text or Markdown content.

Requires: reportlab  (pip install reportlab)
   OR:    fpdf2       (pip install fpdf2)

If neither is installed the tool returns instructions and generates an HTML
fallback that can be printed to PDF from any browser.
"""
from __future__ import annotations
import os, re, logging, textwrap
from pathlib import Path

logger = logging.getLogger(__name__)

_OUTPUT_DIR = Path(__file__).parent.parent / "agent_output" / "pdfs"


def pdf_tool(
    action: str = "create",
    content: str = "",
    filename: str = "output.pdf",
    title: str = "",
    font_size: str = "12",
) -> str:
    """
    Generate PDF files from text or Markdown content.

    action    : create | from_markdown | html_fallback | check
    content   : The text / Markdown to render.
    filename  : Output filename (saved to agent_output/pdfs/).
                Defaults to 'output.pdf'.
    title     : Optional title shown at the top of the PDF.
    font_size : Body font size in points (default 12).

    Actions:
        create        : Create a plain-text PDF from 'content'.
        from_markdown : Convert Markdown 'content' to a formatted PDF
                        (headings, bold, lists, code blocks).
        html_fallback : Always generate an HTML file you can print-to-PDF
                        in any browser (no library required).
        check         : Show which PDF libraries are available.
    """
    if not action or not isinstance(action, str):
        return "Error: 'action' is required."

    action = action.strip().lower()

    if action == "check":
        return _check_libraries()

    if action == "html_fallback":
        return _html_fallback(content, filename.replace(".pdf", ".html"), title)

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_filename(filename)
    out_path  = _OUTPUT_DIR / safe_name

    # Try reportlab first, then fpdf2, then fall back to HTML
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Preformatted
        from reportlab.lib.enums import TA_LEFT, TA_CENTER
        from reportlab.lib import colors

        pdf_path = out_path.with_suffix(".pdf")

        if action == "from_markdown":
            result = _reportlab_markdown(content, pdf_path, title, int(font_size))
        else:
            result = _reportlab_plain(content, pdf_path, title, int(font_size))
        return result

    except ImportError:
        pass

    try:
        from fpdf import FPDF  # type: ignore
        pdf_path = out_path.with_suffix(".pdf")
        if action == "from_markdown":
            result = _fpdf_markdown(content, pdf_path, title, int(font_size))
        else:
            result = _fpdf_plain(content, pdf_path, title, int(font_size))
        return result

    except ImportError:
        pass

    # Neither library available — generate HTML fallback + instructions
    html_path = out_path.with_suffix(".html")
    html_result = _html_fallback(content, html_path.name, title)
    return (
        "⚠ No PDF library found.\n\n"
        "To enable PDF generation, install one of:\n"
        "  pip install reportlab\n"
        "  pip install fpdf2\n\n"
        "In the meantime, an HTML file was generated instead:\n"
        + html_result
    )


# ── reportlab implementations ─────────────────────────────────────────────────

def _reportlab_plain(content: str, path: Path, title: str, font_size: int) -> str:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

    doc  = SimpleDocTemplate(str(path), pagesize=A4,
                             leftMargin=2*cm, rightMargin=2*cm,
                             topMargin=2.5*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    story  = []

    if title:
        story.append(Paragraph(title, styles["Title"]))
        story.append(Spacer(1, 0.4*cm))

    body_style = ParagraphStyle("body", fontSize=font_size, leading=font_size * 1.4,
                                 spaceAfter=6, parent=styles["Normal"])
    for para in content.split("\n\n"):
        text = para.strip().replace("\n", " ")
        if text:
            story.append(Paragraph(text, body_style))
            story.append(Spacer(1, 0.2*cm))

    doc.build(story)
    return f"PDF created: {path}\nSize: {_human_size(path.stat().st_size)}"


def _reportlab_markdown(content: str, path: Path, title: str, font_size: int) -> str:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Preformatted
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib import colors

    doc    = SimpleDocTemplate(str(path), pagesize=A4,
                               leftMargin=2*cm, rightMargin=2*cm,
                               topMargin=2.5*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    story  = []

    if title:
        story.append(Paragraph(title, styles["Title"]))
        story.append(Spacer(1, 0.4*cm))

    body_s  = ParagraphStyle("md_body", fontSize=font_size, leading=font_size*1.4,
                              spaceAfter=4, parent=styles["Normal"])
    h1_s    = ParagraphStyle("md_h1",  fontSize=font_size+8, leading=(font_size+8)*1.3,
                              spaceBefore=10, spaceAfter=6, textColor=colors.HexColor("#1a1a2e"),
                              parent=styles["Heading1"])
    h2_s    = ParagraphStyle("md_h2",  fontSize=font_size+4, leading=(font_size+4)*1.3,
                              spaceBefore=8, spaceAfter=4, parent=styles["Heading2"])
    h3_s    = ParagraphStyle("md_h3",  fontSize=font_size+2, leading=(font_size+2)*1.3,
                              spaceBefore=6, spaceAfter=4, parent=styles["Heading3"])
    code_s  = ParagraphStyle("md_code", fontName="Courier", fontSize=font_size-1,
                              backColor=colors.HexColor("#f4f4f4"),
                              leftIndent=12, spaceBefore=4, spaceAfter=4, parent=styles["Normal"])
    li_s    = ParagraphStyle("md_li",  fontSize=font_size, leftIndent=16,
                              leading=font_size*1.4, spaceAfter=2, parent=styles["Normal"])

    in_code_block = False
    code_buf: list[str] = []

    for line in content.splitlines():
        # Fenced code blocks
        if line.strip().startswith("```"):
            if in_code_block:
                story.append(Preformatted("\n".join(code_buf), code_s))
                story.append(Spacer(1, 0.1*cm))
                code_buf = []
                in_code_block = False
            else:
                in_code_block = True
            continue
        if in_code_block:
            code_buf.append(line)
            continue

        # Headings
        m = re.match(r"^(#{1,3})\s+(.*)", line)
        if m:
            lvl, text = len(m.group(1)), _rl_inline(m.group(2))
            style = {1: h1_s, 2: h2_s, 3: h3_s}.get(lvl, h3_s)
            story.append(Paragraph(text, style))
            continue

        # List items
        m_li = re.match(r"^\s*[-*+]\s+(.*)", line)
        if m_li:
            story.append(Paragraph("• " + _rl_inline(m_li.group(1)), li_s))
            continue

        # Blank line
        if not line.strip():
            story.append(Spacer(1, 0.15*cm))
            continue

        story.append(Paragraph(_rl_inline(line), body_s))

    # flush unclosed code block
    if code_buf:
        story.append(Preformatted("\n".join(code_buf), code_s))

    doc.build(story)
    return f"PDF created (Markdown): {path}\nSize: {_human_size(path.stat().st_size)}"


def _rl_inline(text: str) -> str:
    """Convert inline Markdown to ReportLab XML markup."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*{2}(.+?)\*{2}", r"<b>\1</b>",  text)
    text = re.sub(r"_{2}(.+?)_{2}",   r"<b>\1</b>",  text)
    text = re.sub(r"\*(.+?)\*",       r"<i>\1</i>",  text)
    text = re.sub(r"_(.+?)_",         r"<i>\1</i>",  text)
    text = re.sub(r"`(.+?)`",         r"<font name='Courier'>\1</font>", text)
    return text


# ── fpdf2 implementations ─────────────────────────────────────────────────────

def _fpdf_plain(content: str, path: Path, title: str, font_size: int) -> str:
    from fpdf import FPDF  # type: ignore
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    if title:
        pdf.set_font("Helvetica", "B", font_size + 6)
        pdf.cell(0, 12, title, ln=True, align="C")
        pdf.ln(4)
    pdf.set_font("Helvetica", size=font_size)
    for para in content.split("\n\n"):
        text = " ".join(para.split())
        if text:
            pdf.multi_cell(0, font_size * 0.5 + 2, text)
            pdf.ln(2)
    pdf.output(str(path))
    return f"PDF created: {path}\nSize: {_human_size(path.stat().st_size)}"


def _fpdf_markdown(content: str, path: Path, title: str, font_size: int) -> str:
    """Simplified Markdown rendering with fpdf2."""
    from fpdf import FPDF  # type: ignore
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    if title:
        pdf.set_font("Helvetica", "B", font_size + 8)
        pdf.cell(0, 14, title, ln=True, align="C")
        pdf.ln(4)

    in_code = False
    for line in content.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            pdf.set_font("Courier", size=font_size - 1)
            pdf.set_fill_color(244, 244, 244)
            pdf.multi_cell(0, font_size * 0.45 + 2, line, fill=True)
            continue
        m_h = re.match(r"^(#{1,3})\s+(.*)", line)
        if m_h:
            lvl   = len(m_h.group(1))
            fsize = [font_size + 8, font_size + 4, font_size + 2][lvl - 1]
            pdf.set_font("Helvetica", "B", fsize)
            pdf.ln(2)
            pdf.multi_cell(0, fsize * 0.5 + 2, re.sub(r"[*_`]", "", m_h.group(2)))
            pdf.ln(1)
            continue
        m_li = re.match(r"^\s*[-*+]\s+(.*)", line)
        if m_li:
            pdf.set_font("Helvetica", size=font_size)
            pdf.multi_cell(0, font_size * 0.45 + 2, "  • " + re.sub(r"[*_`]", "", m_li.group(1)))
            continue
        if not line.strip():
            pdf.ln(2)
            continue
        pdf.set_font("Helvetica", size=font_size)
        pdf.multi_cell(0, font_size * 0.45 + 2, re.sub(r"[*_`]", "", line))

    pdf.output(str(path))
    return f"PDF created (Markdown, fpdf2): {path}\nSize: {_human_size(path.stat().st_size)}"


# ── HTML fallback ─────────────────────────────────────────────────────────────

def _html_fallback(content: str, filename: str, title: str) -> str:
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_filename(filename).replace(".pdf", ".html")
    out_path  = _OUTPUT_DIR / safe_name

    escaped = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Very basic Markdown → HTML for readability
    lines = []
    for line in escaped.splitlines():
        m = re.match(r"^(#{1,3})\s+(.*)", line)
        if m:
            lvl = len(m.group(1))
            lines.append(f"<h{lvl}>{m.group(2)}</h{lvl}>")
        elif re.match(r"^\s*[-*+]\s+", line):
            lines.append("<li>" + re.sub(r"^\s*[-*+]\s+", "", line) + "</li>")
        elif not line.strip():
            lines.append("<br>")
        else:
            lines.append(f"<p>{line}</p>")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8">
<title>{title or "Document"}</title>
<style>
  body {{ font-family: Georgia, serif; max-width: 800px; margin: 40px auto;
          padding: 20px; line-height: 1.6; color: #222; }}
  h1, h2, h3 {{ color: #1a1a2e; }}
  pre {{ background: #f4f4f4; padding: 12px; border-radius: 4px; overflow-x: auto; }}
  code {{ font-family: Courier, monospace; }}
  @media print {{
    body {{ margin: 0; padding: 0; }}
    @page {{ margin: 2cm; }}
  }}
</style>
</head>
<body>
{"<h1>" + title + "</h1>" if title else ""}
{"".join(lines)}
</body>
</html>"""

    out_path.write_text(html, encoding="utf-8")
    return (
        f"HTML document created: {out_path}\n"
        f"Open in browser and use File → Print → Save as PDF."
    )


# ── utilities ─────────────────────────────────────────────────────────────────

def _check_libraries() -> str:
    lines = ["PDF Library Status:"]
    for lib in ("reportlab", "fpdf"):
        try:
            __import__(lib)
            lines.append(f"  ✔ {lib} — available")
        except ImportError:
            lines.append(f"  ✘ {lib} — not installed  (pip install {lib if lib != 'fpdf' else 'fpdf2'})")
    lines.append(f"\nOutput directory: {_OUTPUT_DIR}")
    return "\n".join(lines)


def _safe_filename(name: str) -> str:
    name = Path(name).name  # strip directories
    name = re.sub(r"[^\w\-. ]", "_", name).strip()
    return name or "output.pdf"


def _human_size(size: float) -> str:
    for unit in ["B", "KB", "MB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"
