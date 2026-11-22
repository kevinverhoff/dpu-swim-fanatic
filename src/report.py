"""Generate Markdown reports and GitHub Pages JSON payloads for evaluated swim meets."""

from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Any


def generate_markdown_report(
    evaluated_meets: list[dict[str, Any]],
    benchmarks: dict[str, Any],
    settings: dict[str, Any],
) -> str:
    """Create a scannable Markdown summary of notable DePauw swims across meets."""
    season = settings["seasons"]["current_season"]
    prior = settings["seasons"]["prior_season"]
    now_str = time.strftime("%Y-%m-%d %H:%M ET")

    lines = [
        f"# DePauw Swim Fanatic — Notable Swims Report ({season})",
        f"_Last updated: {now_str} | Benchmarks: {season} NCAC Top 16 (Relays Top 8), {season} NCAA DIII Top 16 (Relays Top 8), & {prior} NCAA Nationals Invited Line_",
        "",
    ]

    for meet in evaluated_meets:
        s = meet["summary"]
        lines.append(f"## {meet['meet_name']}")
        lines.append(
            f"- **Source**: {meet['source']} | **Swims Evaluated**: {s['total_swims']} "
            f"| **Notable / On-Bubble**: **{s['notable_swims']}** "
            f"(🏆 Nationals/B-Cut: **{s['nationals_level']}**, 🇺🇸 DIII Top 16/8: **{s['d3_top']}**, "
            f"🐯 NCAC Top 16/8: **{s['ncac_top']}** [Top 8 A-Final: **{s['ncac_a_final']}**], "
            f"🔥 On the Bubble: **{s['on_bubble']}**)"
        )
        lines.append("")

        notable = [e for e in meet["entries"] if e["is_notable"]]
        if not notable:
            lines.append("_No swims currently loaded or matching thresholds for this meet yet._")
            lines.append("")
            continue

        lines.append(
            "| Gender | Swimmer / Relay | Event | Fastest Time | Round (Prelim / Finals) | NCAC Rank (Cut) | DIII Rank (Cut) | '26 Nationals Cut (Delta) | Notable Badges |"
        )
        lines.append(
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |"
        )

        for e in notable:
            rounds_detail = e["best_round"]
            if e["prelim_time_str"] and e["finals_time_str"]:
                flag = " ⚡*(P)*" if e["faster_in_prelims"] else ""
                rounds_detail = f"**{e['best_round']}**{flag} (`P: {e['prelim_time_str']}` / `F: {e['finals_time_str']}`)"
            elif e["time_trial_str"]:
                rounds_detail = f"**Time Trial** (`{e['time_trial_str']}`)"

            ncac_col = (
                f"**#{e['ncac_rank']}** (`{e['ncac_cutoff_str']}`)"
                if e["ncac_rank"]
                else f"— (`{e['ncac_cutoff_str']}`, `{e['ncac_delta_str']}`)"
            )
            d3_col = (
                f"**#{e['d3_rank']}** (`{e['d3_cutoff_str']}`)"
                if e["d3_rank"]
                else f"— (`{e['d3_cutoff_str']}`, `{e['d3_delta_str']}`)"
            )
            nat_col = f"`{e['nationals_invited_str']}` (`{e['nationals_delta_str']}`)"
            badge_str = " · ".join(b["label"] for b in e["badges"])
            swimmer_disp = e["swimmer_name"]
            if e["year"]:
                swimmer_disp += f" ({e['year']})"

            lines.append(
                f"| {e['gender_label']} | **{swimmer_disp}** | {e['event_label']} | **`{e['best_time_str']}`** | {rounds_detail} | {ncac_col} | {d3_col} | {nat_col} | {badge_str} |"
            )

        lines.append("")

    return "\n".join(lines)


def write_dashboard_payload(
    evaluated_meets: list[dict[str, Any]],
    benchmarks: dict[str, Any],
    settings: dict[str, Any],
    output_json_path: Path,
    output_js_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Write the JSON payload consumed by the GitHub Pages interactive dashboard."""
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "team": settings["team"],
        "seasons": settings["seasons"],
        "thresholds": settings["thresholds"],
        "benchmarks": benchmarks,
        "meets": evaluated_meets,
    }
    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(payload, indent=2)
    output_json_path.write_text(json_text, encoding="utf-8")
    if output_js_path:
        output_js_path.write_text(f"window.DPU_SWIM_DATA = {json_text};\n", encoding="utf-8")
    return payload
