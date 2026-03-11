"""csv_tool — Read, summarize, and query CSV data."""
from __future__ import annotations
import csv, io, logging
from pathlib import Path

logger = logging.getLogger(__name__)

def csv_tool(action: str, source: str, query: str = "") -> str:
    """
    Perform CSV operations.

    Args:
        action : read | columns | summary | search | count
        source : CSV file path OR raw CSV text
        query  : (for 'search') substring to match in any column

    Actions:
        read    : Return the first 20 rows as a formatted table.
        columns : List column headers.
        summary : Row count, column count, first/last row.
        search  : Filter rows containing `query` in any field.
        count   : Return total row count (excluding header).
    """
    if not source:
        return "Error: source cannot be empty."

    # Detect if source is a file path
    p = Path(source)
    try:
        if p.exists() and p.is_file():
            text = p.read_text(encoding="utf-8-sig")
        else:
            text = source
        reader = list(csv.DictReader(io.StringIO(text)))
    except Exception as exc:
        return f"Error reading CSV: {exc}"

    if not reader:
        return "CSV is empty or has no data rows."

    headers = list(reader[0].keys())
    action = (action or "read").strip().lower()

    if action == "columns":
        return "Columns:\n" + "\n".join(f"  {i+1}. {h}" for i, h in enumerate(headers))

    if action == "count":
        return f"Row count: {len(reader)}"

    if action == "summary":
        return (
            f"Rows   : {len(reader)}\n"
            f"Columns: {len(headers)}\n"
            f"Headers: {', '.join(headers)}\n"
            f"First  : {dict(reader[0])}\n"
            f"Last   : {dict(reader[-1])}"
        )

    if action == "search":
        q = (query or "").lower()
        if not q:
            return "Error: 'query' required for search."
        matches = [row for row in reader if any(q in str(v).lower() for v in row.values())]
        if not matches:
            return f"No rows found matching '{query}'."
        lines = ["\t".join(headers)]
        for row in matches[:50]:
            lines.append("\t".join(str(row.get(h, "")) for h in headers))
        return "\n".join(lines) + (f"\n({len(matches)} match(es))" )

    # Default: read (first 20 rows)
    lines = ["\t".join(headers)]
    for row in reader[:20]:
        lines.append("\t".join(str(row.get(h, "")) for h in headers))
    suffix = f"\n({len(reader)} total rows)" if len(reader) > 20 else ""
    return "\n".join(lines) + suffix
