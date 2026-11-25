"""Meet result ingestion adapters:
1. Hy-Tek Real-Time Results live web adapter (e.g., sidearmstats.com/kenyon/swim/)
2. SwimCloud Meet / Team Splashes JSON adapter
3. Local file / text / JSON adapter (for Meet Mobile exports or manual results)
"""

from __future__ import annotations
import json
import re
import urllib.request
from pathlib import Path
from typing import Any, Optional

from .benchmarks import fetch_swimcloud_top_times, HEADERS
from .utils import (
    parse_time,
    format_time,
    normalize_event_title,
    normalize_swimmer_name,
)


def _fetch_text(url: str, retries: int = 3) -> str:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": HEADERS["User-Agent"]})
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            last_err = e
    raise RuntimeError(f"Failed to fetch {url} after {retries} attempts: {last_err}")


INDIV_LINE_RE = re.compile(
    r"^\s*(?P<place>\d+|--)\s+"
    r"(?P<name>[A-Za-z'\-\.\s]+,\s*[A-Za-z'\-\.\s]+?)\s+"
    r"(?P<year>FR|SO|JR|SR|GR|FY|5Y|Grad)?\s+"
    r"(?P<team>[A-Z0-9\-\s]{2,16}?)\s+"
    r"(?P<col1>[xX]?[\d:\.]+|NT|NP|NS|SCR|DQ)?\s*"
    r"(?P<col2>[xX]?[\d:\.]+|NT|NP|NS|SCR|DQ)?\s*"
    r"(?P<pts>\d+(?:\.\d+)?)?\s*$"
)

RELAY_LINE_RE = re.compile(
    r"^\s*(?P<place>\d+|--)\s+"
    r"(?P<team>[A-Z0-9\-\s]{2,18}?)\s+"
    r"'(?P<letter>[A-Z])'\s+"
    r"(?P<col1>[xX]?[\d:\.]+|NT|NP|NS|SCR|DQ)?\s*"
    r"(?P<col2>[xX]?[\d:\.]+|NT|NP|NS|SCR|DQ)?\s*"
    r"(?P<pts>\d+(?:\.\d+)?)?\s*$"
)

RELAY_SWIMMER_RE = re.compile(
    r"\d+\)\s*(?:r:[+\-]?\d+\.\d+\s+)?([A-Za-z'\-\.\s]+,\s*[A-Za-z'\-\.\s]+?)\s+(?:FR|SO|JR|SR|GR|FY|5Y)\b"
)


def parse_hytek_event_html(
    html_text: str,
    target_team_codes: list[str],
    meet_id: str,
    meet_name: str,
    source_file: str = "",
) -> list[dict[str, Any]]:
    """Parse a single Hy-Tek Real-Time Results HTML page into normalized splash dicts."""
    if "Results are not available at this time" in html_text:
        return []

    clean_text = re.sub(r"<[^>]+>", "", html_text)
    lines = [line.rstrip() for line in clean_text.splitlines()]

    gender = None
    event_id = None
    is_time_trial_file = "time trial" in clean_text.lower()
    is_prelim_only_table = False

    for line in lines[:35]:
        if "Event " in line:
            g, eid = normalize_event_title(line)
            if g and eid:
                gender, event_id = g, eid
                if "time trial" in line.lower():
                    is_time_trial_file = True
                break

    if not gender or not event_id:
        return []

    is_relay = event_id.endswith("_REL")
    team_codes_upper = {c.upper() for c in target_team_codes}

    current_section = "Finals" if not is_time_trial_file else "Time Trial"
    splashes: list[dict[str, Any]] = []

    i = 0
    while i < len(lines):
        line = lines[i]

        # Check column header line to see if it's Seed + Prelims or Prelims + Finals
        if "Seed" in line and "Prelims" in line and "Finals" not in line:
            is_prelim_only_table = True
            current_section = "Prelims"
        elif "Prelims" in line and "Finals" in line:
            is_prelim_only_table = False

        # Check section divider lines like === A - Final === or === Preliminaries ===
        sec_match = re.search(r"===\s*(.*?)\s*===", line)
        if sec_match:
            sec_title = sec_match.group(1).strip()
            if "Prelim" in sec_title:
                current_section = "Prelims"
            elif "Time Trial" in sec_title:
                current_section = "Time Trial"
            elif "Final" in sec_title:
                current_section = f"Finals ({sec_title.replace(' - ', '-')})"
            i += 1
            continue

        if is_relay:
            rm = RELAY_LINE_RE.match(line)
            if rm:
                team_code = rm.group("team").strip().upper()
                if team_code in team_codes_upper:
                    letter = rm.group("letter")
                    c1 = rm.group("col1")
                    c2 = rm.group("col2")
                    final_raw = c2 if c2 else c1
                    sec = parse_time(final_raw)

                    # Look ahead up to 4 lines for relay swimmer names
                    members: list[str] = []
                    j = i + 1
                    while j < min(len(lines), i + 6):
                        found = RELAY_SWIMMER_RE.findall(lines[j])
                        if found:
                            members.extend(normalize_swimmer_name(n) for n in found)
                        elif RELAY_LINE_RE.match(lines[j]) or "Team Rankings" in lines[j]:
                            break
                        j += 1

                    if sec is not None:
                        splashes.append({
                            "meet_id": meet_id,
                            "meet_name": meet_name,
                            "gender": gender,
                            "event_id": event_id,
                            "is_relay": True,
                            "swimmer_name": f"DePauw '{letter}' Relay",
                            "relay_letter": letter,
                            "relay_members": members,
                            "year": "",
                            "team": "DePauw",
                            "place": rm.group("place"),
                            "round": "Time Trial" if is_time_trial_file else "Finals",
                            "sub_round": current_section,
                            "time_sec": sec,
                            "time_str": format_time(sec),
                            "seed_or_prelim_sec": parse_time(c1) if c2 else None,
                            "exhibition": str(final_raw).strip().lower().startswith("x"),
                            "source_file": source_file,
                        })
        else:
            im = INDIV_LINE_RE.match(line)
            if im:
                team_code = im.group("team").strip().upper()
                if team_code in team_codes_upper:
                    swimmer = normalize_swimmer_name(im.group("name"))
                    yr = (im.group("year") or "").strip()
                    place = im.group("place")
                    c1 = im.group("col1")
                    c2 = im.group("col2")

                    if is_time_trial_file or "Time Trial" in current_section:
                        raw_time = c2 if c2 else c1
                        sec = parse_time(raw_time)
                        if sec is not None:
                            splashes.append({
                                "meet_id": meet_id,
                                "meet_name": meet_name,
                                "gender": gender,
                                "event_id": event_id,
                                "is_relay": False,
                                "swimmer_name": swimmer,
                                "year": yr,
                                "team": "DePauw",
                                "place": place,
                                "round": "Time Trial",
                                "sub_round": "Time Trial",
                                "time_sec": sec,
                                "time_str": format_time(sec),
                                "exhibition": str(raw_time).strip().lower().startswith("x"),
                                "source_file": source_file,
                            })
                    elif is_prelim_only_table or current_section == "Prelims":
                        # In a Prelims file: col1=Seed, col2=Prelims
                        # In a Finals file under === Preliminaries ===: col1=Prelims, col2=None
                        raw_prelim = c2 if is_prelim_only_table and c2 else c1
                        sec = parse_time(raw_prelim)
                        if sec is not None:
                            splashes.append({
                                "meet_id": meet_id,
                                "meet_name": meet_name,
                                "gender": gender,
                                "event_id": event_id,
                                "is_relay": False,
                                "swimmer_name": swimmer,
                                "year": yr,
                                "team": "DePauw",
                                "place": place,
                                "round": "Prelims",
                                "sub_round": "Prelims",
                                "time_sec": sec,
                                "time_str": format_time(sec),
                                "exhibition": str(raw_prelim).strip().lower().startswith("x"),
                                "source_file": source_file,
                            })
                    else:
                        # Finals table (A-Final, B-Final, C-Final, or Timed Finals like 1650)
                        # col1 = Prelims (or Seed for Timed Finals), col2 = Finals
                        raw_final = c2 if c2 else c1
                        sec_final = parse_time(raw_final)
                        if sec_final is not None:
                            splashes.append({
                                "meet_id": meet_id,
                                "meet_name": meet_name,
                                "gender": gender,
                                "event_id": event_id,
                                "is_relay": False,
                                "swimmer_name": swimmer,
                                "year": yr,
                                "team": "DePauw",
                                "place": place,
                                "round": "Finals",
                                "sub_round": current_section,
                                "time_sec": sec_final,
                                "time_str": format_time(sec_final),
                                "exhibition": str(raw_final).strip().lower().startswith("x"),
                                "source_file": source_file,
                            })
                        # Also capture the prelim time from col1 if this isn't a timed-final event
                        if c2 and event_id not in ("1000_FREE", "1650_FREE"):
                            sec_prelim = parse_time(c1)
                            if sec_prelim is not None:
                                splashes.append({
                                    "meet_id": meet_id,
                                    "meet_name": meet_name,
                                    "gender": gender,
                                    "event_id": event_id,
                                    "is_relay": False,
                                    "swimmer_name": swimmer,
                                    "year": yr,
                                    "team": "DePauw",
                                    "place": "",
                                    "round": "Prelims",
                                    "sub_round": "Prelims",
                                    "time_sec": sec_prelim,
                                    "time_str": format_time(sec_prelim),
                                    "exhibition": False,
                                    "source_file": source_file,
                                })
        i += 1

    return splashes


def fetch_hytek_realtime_meet(
    base_url: str,
    target_team_codes: list[str],
    meet_id: str,
    meet_name: str,
    cache_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """Incremental fetcher for Hy-Tek Real-Time Results (e.g. https://sidearmstats.com/kenyon/swim/).
    Checks evtindex.htm and 261118lastevt.htm first for low-compute polling during live meets.
    """
    base = base_url.rstrip("/")
    idx_html = _fetch_text(f"{base}/evtindex.htm")
    links = re.findall(r'<a href="([^"]+\.htm)"[^>]*>(.*?)</a>', idx_html, re.I | re.S)

    event_files: list[str] = []
    seen_files = set()
    for href, _ in links:
        h = href.strip()
        if "lastevt" in h.lower() or "index" in h.lower() or "main" in h.lower():
            continue
        if h not in seen_files:
            seen_files.add(h)
            event_files.append(h)

    all_splashes: list[dict[str, Any]] = []
    completed_files = 0

    for fname in event_files:
        try:
            ev_html = _fetch_text(f"{base}/{fname}")
            if "Results are not available at this time" not in ev_html:
                completed_files += 1
                parsed = parse_hytek_event_html(
                    ev_html,
                    target_team_codes=target_team_codes,
                    meet_id=meet_id,
                    meet_name=meet_name,
                    source_file=fname,
                )
                all_splashes.extend(parsed)
        except Exception as e:
            print(f"[warn] Failed to fetch {base}/{fname}: {e}")

    return {
        "meet_id": meet_id,
        "meet_name": meet_name,
        "source": f"Hy-Tek Live ({base})",
        "total_event_files": len(event_files),
        "completed_event_files": completed_files,
        "is_live_or_active": 0 < completed_files < (len(event_files) - 4),
        "splashes": all_splashes,
    }


def fetch_swimcloud_meet_for_team(
    settings: dict[str, Any],
    swimcloud_meet_id: int,
    meet_id: str,
    meet_name: str,
) -> dict[str, Any]:
    """Fetch all team splashes for a specific SwimCloud meet_id using /api/splashes/top_times/?dont_group=true."""
    team_id = int(settings["team"]["swimcloud_team_id"])
    season_id = int(settings["seasons"]["swimcloud_season_id"])
    splashes: list[dict[str, Any]] = []

    round_map = {
        "PRE": "Prelims",
        "FIN": "Finals",
        "TIM": "Finals",
        "TT": "Time Trial",
        "SO": "Swim-Off",
    }

    for gender in ("F", "M"):
        for ev in settings["events"]:
            ev_id = ev["id"]
            ev_code = ev["swimcloud_code"]
            is_relay = bool(ev["is_relay"])
            try:
                rows = fetch_swimcloud_top_times(
                    event_code=ev_code,
                    gender=gender,
                    season_id=season_id,
                    team_id=team_id,
                    dont_group=True,
                    max_pages=4,
                )
            except Exception:
                rows = []

            for r in rows:
                if int(r.get("meet_id") or 0) != int(swimcloud_meet_id):
                    continue
                sec = parse_time(r.get("eventtime"))
                if sec is None:
                    continue
                sw_obj = r.get("swimmer") or {}
                rel_letter = str(r.get("relayname") or "A").strip()
                sw_name = (
                    f"DePauw '{rel_letter}' Relay"
                    if is_relay
                    else (sw_obj.get("display_name") or r.get("display_name") or "DePauw Swimmer")
                )
                raw_round = str(r.get("eventround") or "FIN").upper()
                norm_round = round_map.get(raw_round, "Finals")

                splashes.append({
                    "meet_id": meet_id,
                    "meet_name": meet_name,
                    "gender": gender,
                    "event_id": ev_id,
                    "is_relay": is_relay,
                    "swimmer_name": sw_name,
                    "year": "",
                    "team": "DePauw",
                    "place": str(r.get("place") or ""),
                    "round": norm_round,
                    "sub_round": norm_round,
                    "time_sec": sec,
                    "time_str": format_time(sec),
                    "exhibition": bool(r.get("exhibition")),
                    "date": r.get("dateofswim"),
                    "source_file": f"swimcloud:{swimcloud_meet_id}",
                })

    return {
        "meet_id": meet_id,
        "meet_name": meet_name,
        "source": f"SwimCloud API (Meet #{swimcloud_meet_id})",
        "total_event_files": len(settings["events"]) * 2,
        "completed_event_files": len(settings["events"]) * 2 if splashes else 0,
        "is_live_or_active": False,
        "splashes": splashes,
    }
