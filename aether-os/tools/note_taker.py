"""note_taker — Persistent session notes that agents can save and search."""
from __future__ import annotations
import json, logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Notes are stored next to this file in a sibling data directory
_NOTES_DIR  = Path(__file__).parent.parent / "agent_output" / "notes"
_NOTES_FILE = _NOTES_DIR / "notes.json"


def note_taker(action: str = "list", content: str = "", tag: str = "") -> str:
    """
    Save and retrieve short notes.

    action  : add | list | search | get | delete | clear
    content : Note text (for 'add'), or note ID (for 'delete').
    tag     : Optional tag to categorize a note (for 'add') or filter (for 'list'/'search').

    Actions:
        add    : Save a new note.  content = note text.
        list   : List all notes, optionally filtered by tag.
        search : Full-text search in note content.
        get    : Show a single note by ID.  content = note ID.
        delete : Remove a note by ID.       content = note ID.
        clear  : Delete ALL notes (irreversible).
    """
    action = (action or "list").strip().lower()

    _NOTES_DIR.mkdir(parents=True, exist_ok=True)
    notes = _load()

    if action == "add":
        if not content.strip():
            return "Error: 'content' is required for 'add'."
        note_id = _next_id(notes)
        note = {
            "id":      str(note_id),
            "content": content.strip(),
            "tag":     tag.strip().lower() if tag else "general",
            "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        notes.append(note)
        _save(notes)
        return f"Note #{note_id} saved.  Tag: {note['tag']}"

    if action == "list":
        filtered = notes
        if tag.strip():
            filtered = [n for n in notes if n.get("tag") == tag.strip().lower()]
        if not filtered:
            return "No notes found." + (f" (tag: {tag})" if tag else "")
        return "\n".join(_fmt_note(n) for n in filtered[-50:])

    if action == "search":
        if not content.strip():
            return "Error: 'content' is required for 'search' (it is the search query)."
        q = content.strip().lower()
        hits = [n for n in notes if q in n.get("content", "").lower()]
        if not hits:
            return f"No notes found matching '{content}'."
        return "\n".join(_fmt_note(n) for n in hits[:50])

    if action == "get":
        if not content.strip():
            return "Error: 'content' must be the note ID."
        n = _by_id(notes, content.strip())
        if n is None:
            return f"No note with ID '{content}'."
        return _fmt_note(n)

    if action == "delete":
        if not content.strip():
            return "Error: 'content' must be the note ID to delete."
        before = len(notes)
        notes = [n for n in notes if n.get("id") != content.strip()]
        if len(notes) == before:
            return f"No note found with ID '{content}'."
        _save(notes)
        return f"Note #{content} deleted."

    if action == "clear":
        _save([])
        return f"All {len(notes)} note(s) cleared."

    return f"Unknown action '{action}'. Use: add, list, search, get, delete, clear."


# ── helpers ──────────────────────────────────────────────────────────────────

def _load() -> list[dict]:
    if not _NOTES_FILE.exists():
        return []
    try:
        return json.loads(_NOTES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(notes: list[dict]) -> None:
    _NOTES_FILE.write_text(json.dumps(notes, indent=2, ensure_ascii=False), encoding="utf-8")


def _next_id(notes: list[dict]) -> int:
    if not notes:
        return 1
    ids = [int(n.get("id", 0)) for n in notes if str(n.get("id", "")).isdigit()]
    return max(ids, default=0) + 1


def _by_id(notes: list[dict], note_id: str) -> dict | None:
    for n in notes:
        if str(n.get("id")) == note_id:
            return n
    return None


def _fmt_note(n: dict) -> str:
    return (
        f"[#{n.get('id')}] [{n.get('tag','?')}] {n.get('created','')}\n"
        f"  {n.get('content','')}"
    )
