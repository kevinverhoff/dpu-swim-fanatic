"""Time parsing, formatting, and event normalization utilities."""

from __future__ import annotations
import re
from typing import Optional


def parse_time(val: str | float | int | None) -> Optional[float]:
    """Convert a swim time ('1:50.69', '23.45', '112.03', 112.03) into seconds (float).
    Returns None for DQ, NS, SCR, NT, X-only, or invalid strings.
    """
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val) if val > 0 else None

    s = str(val).strip()
    if not s:
        return None

    # Strip leading 'x' or 'X' (exhibition prefix in Hy-Tek) and trailing record/cut markers (!, %, *, A, B)
    s = re.sub(r"^[xX]", "", s).strip()
    s = re.sub(r"[!%*#@A-Za-z]+$", "", s).strip()

    if not s or any(tok in s.upper() for tok in ("DQ", "NS", "SCR", "NT", "DNF", "DFS")):
        return None

    try:
        if ":" in s:
            parts = s.split(":")
            if len(parts) == 2:
                mins = int(parts[0])
                secs = float(parts[1])
                return round(mins * 60.0 + secs, 2)
            elif len(parts) == 3:
                hrs = int(parts[0])
                mins = int(parts[1])
                secs = float(parts[2])
                return round(hrs * 3600.0 + mins * 60.0 + secs, 2)
        return round(float(s), 2)
    except ValueError:
        return None


def format_time(seconds: Optional[float]) -> str:
    """Format seconds (float) back into standard swim notation (MM:SS.ss or SS.ss)."""
    if seconds is None or seconds <= 0:
        return "—"
    seconds = round(float(seconds), 2)
    if seconds >= 60.0:
        mins = int(seconds // 60)
        rem = seconds - (mins * 60)
        return f"{mins}:{rem:05.2f}"
    return f"{seconds:05.2f}" if seconds >= 10.0 else f"{seconds:04.2f}"


def format_delta(swim_sec: float, target_sec: float) -> str:
    """Format difference (swim_sec - target_sec) with explicit sign."""
    diff = round(swim_sec - target_sec, 2)
    sign = "+" if diff > 0 else ""
    return f"{sign}{diff:.2f}s"


EVENT_PATTERNS = [
    (re.compile(r"\b200\b.*\b(?:free|freestyle)\s+relay\b", re.I), "200_FR_REL"),
    (re.compile(r"\b400\b.*\b(?:free|freestyle)\s+relay\b", re.I), "400_FR_REL"),
    (re.compile(r"\b800\b.*\b(?:free|freestyle)\s+relay\b", re.I), "800_FR_REL"),
    (re.compile(r"\b200\b.*\bmedley\s+relay\b", re.I), "200_MR_REL"),
    (re.compile(r"\b400\b.*\bmedley\s+relay\b", re.I), "400_MR_REL"),
    (re.compile(r"\b50\b.*\b(?:free|freestyle)\b", re.I), "50_FREE"),
    (re.compile(r"\b100\b.*\b(?:free|freestyle)\b", re.I), "100_FREE"),
    (re.compile(r"\b200\b.*\b(?:free|freestyle)\b", re.I), "200_FREE"),
    (re.compile(r"\b500\b.*\b(?:free|freestyle)\b", re.I), "500_FREE"),
    (re.compile(r"\b1000\b.*\b(?:free|freestyle)\b", re.I), "1000_FREE"),
    (re.compile(r"\b1650\b.*\b(?:free|freestyle)\b", re.I), "1650_FREE"),
    (re.compile(r"\b100\b.*\b(?:back|backstroke)\b", re.I), "100_BACK"),
    (re.compile(r"\b200\b.*\b(?:back|backstroke)\b", re.I), "200_BACK"),
    (re.compile(r"\b100\b.*\b(?:breast|breaststroke)\b", re.I), "100_BREAST"),
    (re.compile(r"\b200\b.*\b(?:breast|breaststroke)\b", re.I), "200_BREAST"),
    (re.compile(r"\b100\b.*\b(?:fly|butterfly)\b", re.I), "100_FLY"),
    (re.compile(r"\b200\b.*\b(?:fly|butterfly)\b", re.I), "200_FLY"),
    (re.compile(r"\b200\b.*\b(?:im|individual\s+medley)\b", re.I), "200_IM"),
    (re.compile(r"\b400\b.*\b(?:im|individual\s+medley)\b", re.I), "400_IM"),
]


def normalize_event_title(title: str) -> tuple[Optional[str], Optional[str]]:
    """Extract (gender, event_id) from a Hy-Tek event header like 'Event 17 Women 100 Yard Butterfly'."""
    t = title.strip()
    gender = None
    if re.search(r"\b(?:women|female|girls)\b", t, re.I):
        gender = "F"
    elif re.search(r"\b(?:men|male|boys)\b", t, re.I):
        gender = "M"

    event_id = None
    for pat, eid in EVENT_PATTERNS:
        if pat.search(t):
            event_id = eid
            break

    return gender, event_id


def normalize_swimmer_name(raw_name: str) -> str:
    """Convert Hy-Tek 'Last, First' into 'First Last'."""
    name = raw_name.strip()
    if "," in name:
        parts = [p.strip() for p in name.split(",", 1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            return f"{parts[1]} {parts[0]}"
    return name
