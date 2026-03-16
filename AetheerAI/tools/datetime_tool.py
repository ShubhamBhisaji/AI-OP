"""datetime_tool — Parse, format, compare, and manipulate dates and times."""
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_FMT_ISO   = "%Y-%m-%d %H:%M:%S"
_FMT_DATE  = "%Y-%m-%d"
_FMT_NICE  = "%B %d, %Y %I:%M %p"
_FMT_SHORT = "%d/%m/%Y"

_COMMON_FMTS = [_FMT_ISO, _FMT_DATE, _FMT_NICE, _FMT_SHORT,
                "%m/%d/%Y", "%d-%m-%Y", "%Y%m%d", "%I:%M %p",
                "%H:%M:%S", "%H:%M", "%d %b %Y", "%d %B %Y"]


def datetime_tool(action: str = "now", value: str = "", fmt: str = "") -> str:
    """
    Date and time utilities.

    action : now | parse | format | diff | add | day_of_week | timestamp
    value  : Date/time string (context depends on action).
    fmt    : Output format string for 'format' action (strftime codes).

    Actions:
        now         : Current date and time in UTC and local time.
        parse       : Parse a date/time string and show its components.
        format      : Reformat a date/time string with a custom format string.
        diff        : Show the difference between two dates separated by " | ".
        add         : Add duration to a date — value: "DATE | NUMunit"
                       e.g. "2024-01-01 | 30days"  (units: days/hours/minutes/weeks).
        day_of_week : Day name for a date string.
        timestamp   : Unix timestamp ↔ human date.
                       If value is numeric → human. Otherwise → timestamp.
    """
    action = (action or "now").strip().lower()

    if action == "now":
        utc  = datetime.now(timezone.utc)
        local = datetime.now()
        return (
            f"UTC  : {utc.strftime(_FMT_ISO)} Z\n"
            f"Local: {local.strftime(_FMT_ISO)}\n"
            f"Unix : {int(utc.timestamp())}"
        )

    if action == "parse":
        if not value.strip():
            return "Error: 'value' is required for 'parse'."
        dt = _try_parse(value)
        if dt is None:
            return f"Error: Could not parse '{value}'. Try ISO format: YYYY-MM-DD HH:MM:SS."
        return (
            f"Input    : {value}\n"
            f"Year     : {dt.year}\n"
            f"Month    : {dt.month} ({dt.strftime('%B')})\n"
            f"Day      : {dt.day}\n"
            f"Weekday  : {dt.strftime('%A')}\n"
            f"Hour     : {dt.hour}\n"
            f"Minute   : {dt.minute}\n"
            f"Second   : {dt.second}\n"
            f"ISO      : {dt.strftime(_FMT_ISO)}"
        )

    if action == "format":
        if not value.strip():
            return "Error: 'value' (date string) is required."
        if not fmt.strip():
            return "Error: 'fmt' (strftime format string) is required. Example: '%B %d, %Y'."
        dt = _try_parse(value)
        if dt is None:
            return f"Error: Could not parse date '{value}'."
        try:
            return dt.strftime(fmt)
        except Exception as e:
            return f"Error applying format: {e}"

    if action == "diff":
        if not value.strip() or "|" not in value:
            return "Error: 'value' must be two dates separated by ' | ' e.g. '2024-01-01 | 2025-06-01'."
        parts = value.split("|", 1)
        dt1 = _try_parse(parts[0].strip())
        dt2 = _try_parse(parts[1].strip())
        if dt1 is None: return f"Error: Could not parse first date '{parts[0].strip()}'."
        if dt2 is None: return f"Error: Could not parse second date '{parts[1].strip()}'."
        delta = dt2 - dt1
        sign  = "later" if delta.total_seconds() >= 0 else "earlier"
        absd  = abs(delta)
        total_secs = int(absd.total_seconds())
        d = absd.days
        h = total_secs // 3600 % 24
        m = total_secs % 3600 // 60
        return (
            f"From    : {dt1.strftime(_FMT_ISO)}\n"
            f"To      : {dt2.strftime(_FMT_ISO)}\n"
            f"Delta   : {d} days, {h} hours, {m} minutes\n"
            f"Direction: date2 is {sign} than date1"
        )

    if action == "add":
        if not value.strip() or "|" not in value:
            return "Error: 'value' must be 'DATE | NUMunit', e.g. '2024-01-01 | 30days'."
        parts = value.split("|", 1)
        dt = _try_parse(parts[0].strip())
        if dt is None:
            return f"Error: Could not parse date '{parts[0].strip()}'."
        dur_str = parts[1].strip().lower()
        td = _parse_duration(dur_str)
        if td is None:
            return f"Error: Could not parse duration '{dur_str}'. Use formats like '30days', '12hours', '45minutes', '2weeks'."
        result = dt + td
        return f"Original : {dt.strftime(_FMT_ISO)}\nAdded    : {dur_str}\nResult   : {result.strftime(_FMT_ISO)}"

    if action == "day_of_week":
        if not value.strip():
            return "Error: 'value' must be a date string."
        dt = _try_parse(value)
        if dt is None:
            return f"Error: Could not parse '{value}'."
        return f"{value.strip()} → {dt.strftime('%A')}"

    if action == "timestamp":
        if not value.strip():
            return "Error: 'value' is required."
        stripped = value.strip()
        if stripped.lstrip("-").isdigit():
            ts = int(stripped)
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            return f"Unix {ts} → {dt.strftime(_FMT_ISO)} UTC"
        dt = _try_parse(stripped)
        if dt is None:
            return f"Error: Could not parse '{stripped}'."
        utc_dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
        return f"{stripped} → Unix timestamp: {int(utc_dt.timestamp())}"

    return f"Unknown action '{action}'. Use: now, parse, format, diff, add, day_of_week, timestamp."


def _try_parse(s: str) -> datetime | None:
    s = s.strip()
    for fmt in _COMMON_FMTS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def _parse_duration(s: str) -> timedelta | None:
    import re
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*(days?|hours?|minutes?|mins?|seconds?|secs?|weeks?)", s.strip())
    if not m:
        return None
    val  = float(m.group(1))
    unit = m.group(2).rstrip("s")  # normalize plural
    if unit in ("day",):    return timedelta(days=val)
    if unit in ("hour",):   return timedelta(hours=val)
    if unit in ("minute", "min"): return timedelta(minutes=val)
    if unit in ("second", "sec"): return timedelta(seconds=val)
    if unit in ("week",):   return timedelta(weeks=val)
    return None
