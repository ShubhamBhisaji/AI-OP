"""regex_tool — Apply regular expressions to text."""
from __future__ import annotations
import re, json, logging

logger = logging.getLogger(__name__)

_MAX_RESULTS = 200


def regex_tool(pattern: str, text: str, action: str = "findall") -> str:
    """
    Apply a regex pattern to text.

    pattern : Regular expression pattern.
    text    : Input text to operate on.
    action  : match | findall | replace | split | count | groups

    Actions:
        match    : Test if the pattern matches anywhere in the text.
        findall  : Return all non-overlapping matches.
        replace  : Replace all matches with the value in 'text' argument.
                   Format: "ORIGINAL_TEXT|||REPLACEMENT"
        split    : Split text on the pattern.
        count    : Count the number of matches.
        groups   : Show all capturing groups from the first match.
    """
    if not pattern or not isinstance(pattern, str):
        return "Error: 'pattern' is required."
    if not isinstance(text, str):
        text = str(text)

    action = (action or "findall").strip().lower()

    try:
        compiled = re.compile(pattern, re.MULTILINE)
    except re.error as e:
        return f"Error: Invalid regex pattern — {e}"

    if action == "match":
        m = compiled.search(text)
        if m:
            return f"Match found at [{m.start()}:{m.end()}]: '{m.group()}'"
        return "No match found."

    if action == "findall":
        matches = compiled.findall(text)
        if not matches:
            return "No matches found."
        if len(matches) > _MAX_RESULTS:
            matches = matches[:_MAX_RESULTS]
            truncated = True
        else:
            truncated = False
        out = "\n".join(f"  {i+1:3}. {repr(m)}" for i, m in enumerate(matches))
        note = f"\n\n[Showing first {_MAX_RESULTS} matches]" if truncated else ""
        return f"Matches ({len(matches)}):\n{out}{note}"

    if action == "replace":
        if "|||" not in text:
            return "Error: For 'replace', 'text' must be 'ORIGINAL|||REPLACEMENT'."
        original, replacement = text.split("|||", 1)
        result = compiled.sub(replacement, original)
        return result

    if action == "split":
        parts = compiled.split(text)
        if not parts:
            return "(empty result)"
        out = "\n".join(f"  [{i}] {repr(p)}" for i, p in enumerate(parts[:_MAX_RESULTS]))
        return f"Split into {len(parts)} part(s):\n{out}"

    if action == "count":
        count = len(compiled.findall(text))
        return f"Pattern matched {count} time(s)."

    if action == "groups":
        m = compiled.search(text)
        if not m:
            return "No match found — cannot extract groups."
        groups = m.groups()
        named  = m.groupdict()
        out = [f"Full match : '{m.group()}'  [{m.start()}:{m.end()}]"]
        if named:
            out.append("Named groups:")
            for k, v in named.items():
                out.append(f"  {k} = {repr(v)}")
        elif groups:
            out.append("Positional groups:")
            for i, g in enumerate(groups, 1):
                out.append(f"  Group {i} = {repr(g)}")
        else:
            out.append("(no capturing groups in pattern)")
        return "\n".join(out)

    return f"Unknown action '{action}'. Use: match, findall, replace, split, count, groups."
