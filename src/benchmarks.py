"""Fetch and cache NCAC Top 16/Top 8 and NCAA DIII Top 16/Top 8 benchmarks from SwimCloud JSON endpoints."""

from __future__ import annotations
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

from .utils import parse_time, format_time

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


def fetch_swimcloud_top_times(
    event_code: str,
    gender: str,
    season_id: int,
    region: Optional[str] = None,
    team_id: Optional[int] = None,
    dont_group: bool = False,
) -> list[dict[str, Any]]:
    """Query SwimCloud's /api/splashes/top_times/ JSON endpoint."""
    params: dict[str, Any] = {
        "event": event_code,
        "gender": gender,
        "season_id": season_id,
    }
    if region:
        params["region"] = region
    if team_id:
        params["team_id"] = team_id
    if dont_group:
        params["dont_group"] = "true"

    qs = urllib.parse.urlencode(params, safe="|")
    url = f"https://www.swimcloud.com/api/splashes/top_times/?{qs}"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
        return payload.get("results", []) if isinstance(payload, dict) else []


def build_benchmark_ladder(
    raw_results: list[dict[str, Any]],
    is_relay: bool,
    top_n: int,
) -> dict[str, Any]:
    """Extract a deduplicated top-N ladder (1 per swimmer for individual, 1 per team for relay)."""
    ladder = []
    seen_keys = set()

    for item in raw_results:
        sec = parse_time(item.get("eventtime"))
        if sec is None:
            continue

        team_obj = item.get("team") or {}
        swimmer_obj = item.get("swimmer") or {}
        team_name = team_obj.get("name") or item.get("team_name") or item.get("display_name") or "Unknown"
        swimmer_name = swimmer_obj.get("display_name") or item.get("display_name") or team_name

        # Deduplicate 1 per team for relays, 1 per swimmer_id/name for individual events
        if is_relay:
            dedup_key = str(item.get("team_id") or team_name)
        else:
            dedup_key = str(item.get("swimmer_id") or swimmer_name)

        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)

        ladder.append({
            "rank": len(ladder) + 1,
            "name": team_name if is_relay else swimmer_name,
            "team": team_name,
            "team_id": item.get("team_id"),
            "swimmer_id": item.get("swimmer_id"),
            "time_sec": sec,
            "time_str": format_time(sec),
            "date": item.get("dateofswim"),
            "meet_name": item.get("name"),
            "meet_id": item.get("meet_id"),
        })
        if len(ladder) >= max(top_n, 25):
            break

    cutoff_idx = min(top_n, len(ladder)) - 1 if ladder else -1
    cutoff_sec = ladder[cutoff_idx]["time_sec"] if cutoff_idx >= 0 else None

    return {
        "top_n": top_n,
        "count_available": len(ladder),
        "cutoff_rank": cutoff_idx + 1 if cutoff_idx >= 0 else None,
        "cutoff_sec": cutoff_sec,
        "cutoff_str": format_time(cutoff_sec),
        "leader_sec": ladder[0]["time_sec"] if ladder else None,
        "leader_str": ladder[0]["time_str"] if ladder else "—",
        "leader_name": ladder[0]["name"] if ladder else None,
        "leader_team": ladder[0]["team"] if ladder else None,
        "ladder": ladder[:top_n],
    }


def load_or_refresh_benchmarks(
    settings: dict[str, Any],
    cache_path: Path,
    force_refresh: bool = False,
    max_age_hours: float = 6.0,
) -> dict[str, Any]:
    """Load cached season benchmarks or refresh from SwimCloud JSON API if stale/forced."""
    if not force_refresh and cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            fetched_at = cached.get("fetched_epoch", 0)
            if (time.time() - fetched_at) < (max_age_hours * 3600):
                return cached
        except Exception:
            pass

    season_cfg = settings["seasons"]
    season_id = int(season_cfg["swimcloud_season_id"])
    season_label = season_cfg["current_season"]
    conf_region = settings["team"]["conference_region"]
    div_region = settings["team"]["division_region"]
    ind_top_n = int(settings["thresholds"]["individual_top_n"])
    rel_top_n = int(settings["thresholds"]["relay_top_n"])
    ncaa_table = settings.get("ncaa_cutoffs", {}).get(season_label, {})

    benchmarks: dict[str, Any] = {
        "season": season_label,
        "swimcloud_season_id": season_id,
        "fetched_epoch": int(time.time()),
        "fetched_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "events": {"F": {}, "M": {}},
    }

    for gender in ("F", "M"):
        gender_cuts = ncaa_table.get(gender, {})
        for ev in settings["events"]:
            ev_id = ev["id"]
            ev_code = ev["swimcloud_code"]
            is_relay = bool(ev["is_relay"])
            top_n = rel_top_n if is_relay else ind_top_n

            # Fetch NCAC & NCAA D3 top times from SwimCloud JSON endpoint
            try:
                ncac_raw = fetch_swimcloud_top_times(ev_code, gender, season_id, region=conf_region)
            except Exception as e:
                print(f"[warn] NCAC fetch failed for {gender} {ev_id}: {e}")
                ncac_raw = []

            try:
                d3_raw = fetch_swimcloud_top_times(ev_code, gender, season_id, region=div_region)
            except Exception as e:
                print(f"[warn] D3 fetch failed for {gender} {ev_id}: {e}")
                d3_raw = []

            ncac_ladder = build_benchmark_ladder(ncac_raw, is_relay=is_relay, top_n=top_n)
            d3_ladder = build_benchmark_ladder(d3_raw, is_relay=is_relay, top_n=top_n)

            ev_cuts = gender_cuts.get(ev_id, {})
            inv_sec = parse_time(ev_cuts.get("invited_prev"))
            b_sec = parse_time(ev_cuts.get("b_cut"))
            a_sec = parse_time(ev_cuts.get("a_cut"))

            benchmarks["events"][gender][ev_id] = {
                "event_id": ev_id,
                "label": ev["label"],
                "is_relay": is_relay,
                "order": ev["order"],
                "ncac": ncac_ladder,
                "d3": d3_ladder,
                "nationals": {
                    "invited_prev_sec": inv_sec,
                    "invited_prev_str": format_time(inv_sec),
                    "b_cut_sec": b_sec,
                    "b_cut_str": format_time(b_sec),
                    "a_cut_sec": a_sec,
                    "a_cut_str": format_time(a_sec),
                },
            }

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(benchmarks, indent=2), encoding="utf-8")
    return benchmarks
