"""CLI and pipeline runner for dpu-swim-fanatic.
Designed for near-real-time updates during active meets and zero wasted compute when idle.
"""

from __future__ import annotations
import argparse
import datetime
import json
import sys
from pathlib import Path
from typing import Any

from .benchmarks import load_or_refresh_benchmarks
from .meets import fetch_hytek_realtime_meet, fetch_swimcloud_meet_for_team
from .evaluator import evaluate_meet_swims
from .report import generate_markdown_report, write_dashboard_payload


def is_within_active_meet_window(settings: dict[str, Any], today_str: str | None = None) -> bool:
    """Return True if today falls within [start_date - 1 day, end_date + 1 day] of any configured meet."""
    today = datetime.date.fromisoformat(today_str) if today_str else datetime.date.today()
    for m in settings.get("meets", []):
        try:
            start = datetime.date.fromisoformat(m["start_date"]) - datetime.timedelta(days=1)
            end = datetime.date.fromisoformat(m["end_date"]) + datetime.timedelta(days=1)
            if start <= today <= end:
                return True
        except Exception:
            continue
    return False


def run_pipeline(
    repo_root: Path,
    force_benchmarks: bool = False,
    smart_live_gate: bool = False,
    meet_filter: str | None = None,
) -> int:
    settings_path = repo_root / "config" / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))

    if smart_live_gate and not is_within_active_meet_window(settings):
        print("[gate] No active DePauw meet window today. Skipping live poll to save compute.")
        return 0

    cache_path = repo_root / "data" / "cache" / "benchmarks.json"
    print("[1/3] Loading / refreshing NCAC & NCAA DIII benchmarks from SwimCloud JSON API...")
    benchmarks = load_or_refresh_benchmarks(
        settings=settings,
        cache_path=cache_path,
        force_refresh=force_benchmarks,
    )

    evaluated_meets: list[dict[str, Any]] = []
    team_codes = settings["team"]["hytek_codes"]

    print("[2/3] Fetching and evaluating meet results...")
    for m_cfg in settings.get("meets", []):
        mid = m_cfg["id"]
        if meet_filter and meet_filter.lower() not in mid.lower() and meet_filter.lower() not in m_cfg["name"].lower():
            continue

        mname = m_cfg["name"]
        stype = m_cfg.get("source_type", "swimcloud")
        live_url = m_cfg.get("live_url")
        sc_id = m_cfg.get("swimcloud_meet_id")
        local_override = repo_root / "data" / "meets" / f"{mid}.json"

        meet_raw: dict[str, Any] | None = None

        # 1. Try live Hy-Tek Real-Time Results if configured, using cached copy if already complete
        out_meet_cache = repo_root / "data" / "meets" / f"{mid}_cached.json"
        if not force_benchmarks and out_meet_cache.exists():
            try:
                cached_meet = json.loads(out_meet_cache.read_text(encoding="utf-8"))
                if cached_meet.get("splashes") and not cached_meet.get("is_live_or_active", False):
                    meet_raw = cached_meet
                    print(f"  -> Loaded cached completed meet data for {mname} ({len(meet_raw['splashes'])} splashes)")
            except Exception:
                pass

        if not meet_raw and stype == "hytek_realtime" and live_url:
            print(f"  -> Polling Hy-Tek Real-Time Results for {mname} ({live_url})...")
            try:
                meet_raw = fetch_hytek_realtime_meet(
                    base_url=live_url,
                    target_team_codes=team_codes,
                    meet_id=mid,
                    meet_name=mname,
                )
            except Exception as e:
                print(f"  [warn] Live Hy-Tek fetch failed for {mname}: {e}")

        # 2. If no splashes from live URL, check local JSON override or SwimCloud meet ID
        if (not meet_raw or not meet_raw.get("splashes")) and local_override.exists():
            print(f"  -> Loading local meet data from {local_override}...")
            meet_raw = json.loads(local_override.read_text(encoding="utf-8"))

        if (not meet_raw or not meet_raw.get("splashes")) and sc_id:
            print(f"  -> Checking SwimCloud JSON API for {mname} (Meet #{sc_id})...")
            try:
                sc_data = fetch_swimcloud_meet_for_team(
                    settings=settings,
                    swimcloud_meet_id=int(sc_id),
                    meet_id=mid,
                    meet_name=mname,
                )
                if sc_data.get("splashes") or not meet_raw:
                    meet_raw = sc_data
            except Exception as e:
                print(f"  [warn] SwimCloud meet fetch failed for {mname}: {e}")

        if not meet_raw:
            meet_raw = {
                "meet_id": mid,
                "meet_name": mname,
                "source": "Pending upload to SwimCloud / Live Stats",
                "total_event_files": 0,
                "completed_event_files": 0,
                "is_live_or_active": False,
                "splashes": [],
            }

        # Cache normalized meet splashes (don't overwrite non-empty cache with empty splashes)
        if meet_raw.get("splashes") or not out_meet_cache.exists():
            out_meet_cache.parent.mkdir(parents=True, exist_ok=True)
            out_meet_cache.write_text(json.dumps(meet_raw, indent=2), encoding="utf-8")

        evaluated = evaluate_meet_swims(meet_raw, benchmarks, settings)
        evaluated_meets.append(evaluated)
        s = evaluated["summary"]
        print(
            f"     {mname}: {s['total_swims']} unique swimmer/event entries -> "
            f"{s['notable_swims']} notable (Nationals/B: {s['nationals_level']}, "
            f"D3 Top 16/8: {s['d3_top']}, NCAC Top 16/8: {s['ncac_top']}, Bubble: {s['on_bubble']})"
        )

    print("[3/3] Writing Markdown report and GitHub Pages dashboard data...")
    md_report = generate_markdown_report(evaluated_meets, benchmarks, settings)
    report_path = repo_root / "REPORT.md"
    report_path.write_text(md_report, encoding="utf-8")

    dashboard_json = repo_root / "docs" / "data" / "dashboard.json"
    dashboard_js = repo_root / "docs" / "data" / "dashboard.js"
    write_dashboard_payload(
        evaluated_meets,
        benchmarks,
        settings,
        output_json_path=dashboard_json,
        output_js_path=dashboard_js,
    )
    print(f"Done! Report written to {report_path} and dashboard payload to {dashboard_json}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="DePauw Swim Fanatic — Notable Swim Tracker")
    parser.add_argument("--refresh-benchmarks", action="store_true", help="Force refresh of SwimCloud NCAC/DIII benchmarks")
    parser.add_argument("--smart-gate", action="store_true", help="Exit immediately with 0 compute if not inside an active meet date window")
    parser.add_argument("--meet", type=str, default=None, help="Filter to a specific meet ID or name substring")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    return run_pipeline(
        repo_root=repo_root,
        force_benchmarks=args.refresh_benchmarks,
        smart_live_gate=args.smart_gate,
        meet_filter=args.meet,
    )


if __name__ == "__main__":
    sys.exit(main())
