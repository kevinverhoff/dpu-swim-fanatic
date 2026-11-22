"""Evaluate meet swims against NCAC Top 16/Top 8, NCAA DIII Top 16/Top 8, and last year's Nationals cutoff."""

from __future__ import annotations
from typing import Any, Optional
from .utils import format_time, format_delta


def _compute_projected_rank(time_sec: float, ladder: list[dict[str, Any]], swimmer_name: str, is_relay: bool) -> int:
    """Calculate where `time_sec` would rank (1-indexed) on a benchmark ladder."""
    rank = 1
    for entry in ladder:
        # Don't double-count the exact same swimmer/team if they already hold a faster time,
        # or if this swim would displace their slower entry
        same_entity = (
            (is_relay and "depauw" in str(entry.get("team", "")).lower())
            or (not is_relay and entry.get("name", "").lower() == swimmer_name.lower())
        )
        if same_entity:
            if entry["time_sec"] < time_sec:
                rank += 1
            continue
        if entry["time_sec"] < time_sec:
            rank += 1
        else:
            break
    return rank


def evaluate_meet_swims(
    meet_data: dict[str, Any],
    benchmarks: dict[str, Any],
    settings: dict[str, Any],
) -> dict[str, Any]:
    """Group meet splashes by (gender, event_id, swimmer_name), pick fastest swim,
    record prelim/finals history, and classify against all 3 thresholds + On the Bubble.
    """
    bubble_pct = float(settings["thresholds"].get("bubble_pct", 0.015))
    event_meta = {ev["id"]: ev for ev in settings["events"]}

    # Group splashes by (gender, event_id, swimmer_name)
    # For relays, find the fastest DePauw relay per (gender, event_id) so only DePauw's top relay per event is ranked against conference/national 1-per-school ladders
    fastest_relay_by_event: dict[tuple[str, str], str] = {}
    for sp in meet_data.get("splashes", []):
        if sp.get("is_relay"):
            rk = (sp["gender"], sp["event_id"])
            if rk not in fastest_relay_by_event:
                fastest_relay_by_event[rk] = sp["swimmer_name"]
            else:
                # Compare against existing best for that relay event
                prev_best = min(
                    x["time_sec"]
                    for x in meet_data["splashes"]
                    if x.get("is_relay") and (x["gender"], x["event_id"]) == rk and x["swimmer_name"] == fastest_relay_by_event[rk]
                )
                if sp["time_sec"] < prev_best:
                    fastest_relay_by_event[rk] = sp["swimmer_name"]

    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for sp in meet_data.get("splashes", []):
        if sp.get("is_relay"):
            rk = (sp["gender"], sp["event_id"])
            if fastest_relay_by_event.get(rk) != sp["swimmer_name"]:
                continue
        key = (sp["gender"], sp["event_id"], sp["swimmer_name"])
        grouped.setdefault(key, []).append(sp)

    evaluated_entries: list[dict[str, Any]] = []

    for (gender, event_id, swimmer_name), group in grouped.items():
        ev_cfg = event_meta.get(event_id, {})
        ev_bench = benchmarks.get("events", {}).get(gender, {}).get(event_id)
        if not ev_bench:
            continue

        is_relay = bool(ev_bench.get("is_relay"))
        top_n = int(ev_bench["ncac"]["top_n"])

        # Deduplicate rounds (Prelims, Finals, Time Trial) keeping best per round
        by_round: dict[str, dict[str, Any]] = {}
        for sp in group:
            rnd = sp.get("round", "Finals")
            if rnd not in by_round or sp["time_sec"] < by_round[rnd]["time_sec"]:
                by_round[rnd] = sp

        # Find overall fastest swim across all rounds at this meet
        fastest = min(by_round.values(), key=lambda x: x["time_sec"])
        best_sec = fastest["time_sec"]
        best_round = fastest["round"]
        best_sub_round = fastest.get("sub_round", best_round)

        prelim_sp = by_round.get("Prelims")
        finals_sp = by_round.get("Finals")
        tt_sp = by_round.get("Time Trial")

        # Pick best non-empty place from Finals first, then Prelims
        place = (
            (finals_sp.get("place") if finals_sp and finals_sp.get("place") else None)
            or (prelim_sp.get("place") if prelim_sp and prelim_sp.get("place") else None)
            or fastest.get("place")
            or ""
        )

        # Threshold benchmarks
        nat_info = ev_bench.get("nationals", {})
        ncac_info = ev_bench.get("ncac", {})
        d3_info = ev_bench.get("d3", {})

        nat_cut_sec: Optional[float] = nat_info.get("invited_prev_sec")
        b_cut_sec: Optional[float] = nat_info.get("b_cut_sec")
        a_cut_sec: Optional[float] = nat_info.get("a_cut_sec")
        ncac_cut_sec: Optional[float] = ncac_info.get("cutoff_sec")
        d3_cut_sec: Optional[float] = d3_info.get("cutoff_sec")

        ncac_proj_rank = _compute_projected_rank(
            best_sec, ncac_info.get("ladder", []), swimmer_name, is_relay
        )
        d3_proj_rank = _compute_projected_rank(
            best_sec, d3_info.get("ladder", []), swimmer_name, is_relay
        )

        # Boolean achievement flags
        is_nationals_invite = nat_cut_sec is not None and best_sec <= nat_cut_sec
        is_ncaa_b_cut = b_cut_sec is not None and best_sec <= b_cut_sec
        is_ncaa_a_cut = a_cut_sec is not None and best_sec <= a_cut_sec
        is_d3_top = d3_cut_sec is not None and best_sec <= d3_cut_sec
        is_ncac_top = (ncac_cut_sec is not None and best_sec <= ncac_cut_sec) or (
            ncac_info.get("count_available", 0) < top_n and ncac_proj_rank <= top_n
        )
        is_ncac_a_final = is_ncac_top and ncac_proj_rank <= 8

        ncac_display_rank = ncac_proj_rank if is_ncac_top else None
        d3_display_rank = d3_proj_rank if is_d3_top else None

        # Bubble checks (within bubble_pct of any threshold not yet achieved)
        bubble_targets: list[str] = []
        if not is_nationals_invite and nat_cut_sec is not None:
            if best_sec <= nat_cut_sec * (1.0 + bubble_pct):
                bubble_targets.append(f"Nationals Invite ({format_delta(best_sec, nat_cut_sec)})")
        if not is_d3_top and d3_cut_sec is not None:
            if best_sec <= d3_cut_sec * (1.0 + bubble_pct):
                bubble_targets.append(f"DIII Top {top_n} ({format_delta(best_sec, d3_cut_sec)})")
        if not is_ncac_top and ncac_cut_sec is not None:
            if best_sec <= ncac_cut_sec * (1.0 + bubble_pct):
                bubble_targets.append(f"NCAC Top {top_n} ({format_delta(best_sec, ncac_cut_sec)})")

        is_on_bubble = len(bubble_targets) > 0

        # Assign primary tier & badges
        badges: list[dict[str, str]] = []
        if is_nationals_invite:
            badges.append({"id": "nationals_invite", "label": "2026 Nationals Qualifier Line", "tone": "gold"})
        if is_ncaa_a_cut:
            badges.append({"id": "ncaa_a", "label": "NCAA A-Cut", "tone": "gold"})
        elif is_ncaa_b_cut:
            badges.append({"id": "ncaa_b", "label": "NCAA B-Cut", "tone": "amber"})
        if is_d3_top:
            badges.append({"id": "d3_top", "label": f"NCAA DIII #{d3_proj_rank} (Top {top_n})", "tone": "blue"})
        if is_ncac_top:
            tier_label = f"NCAC #{ncac_proj_rank} (Top 8)" if is_ncac_a_final else f"NCAC #{ncac_proj_rank} (Top {top_n})"
            badges.append({"id": "ncac_top", "label": tier_label, "tone": "tiger" if is_ncac_a_final else "green"})
        if is_on_bubble:
            for bt in bubble_targets:
                badges.append({"id": "bubble", "label": f"Bubble: {bt}", "tone": "purple"})

        # Highest tier rank for sorting/filtering
        if is_nationals_invite or is_ncaa_b_cut:
            primary_tier = "NATIONALS"
            tier_priority = 1
        elif is_d3_top:
            primary_tier = "D3_TOP"
            tier_priority = 2
        elif is_ncac_top:
            primary_tier = "NCAC_TOP"
            tier_priority = 3
        elif is_on_bubble:
            primary_tier = "BUBBLE"
            tier_priority = 4
        else:
            primary_tier = "OTHER"
            tier_priority = 5

        evaluated_entries.append({
            "meet_id": meet_data["meet_id"],
            "meet_name": meet_data["meet_name"],
            "gender": gender,
            "gender_label": "Women" if gender == "F" else "Men",
            "event_id": event_id,
            "event_label": ev_cfg.get("label", event_id),
            "event_order": ev_cfg.get("order", 99),
            "is_relay": is_relay,
            "swimmer_name": swimmer_name,
            "relay_members": fastest.get("relay_members", []),
            "year": fastest.get("year", ""),
            "place": place,
            "best_time_sec": best_sec,
            "best_time_str": format_time(best_sec),
            "best_round": best_round,
            "best_sub_round": best_sub_round,
            "prelim_time_str": prelim_sp["time_str"] if prelim_sp else None,
            "finals_time_str": finals_sp["time_str"] if finals_sp else None,
            "time_trial_str": tt_sp["time_str"] if tt_sp else None,
            "faster_in_prelims": bool(
                prelim_sp and finals_sp and prelim_sp["time_sec"] < finals_sp["time_sec"]
            ),
            "ncac_rank": ncac_display_rank,
            "ncac_cutoff_str": ncac_info.get("cutoff_str", "—"),
            "ncac_delta_str": format_delta(best_sec, ncac_cut_sec) if ncac_cut_sec else "—",
            "ncac_delta_sec": round(best_sec - ncac_cut_sec, 2) if ncac_cut_sec else None,
            "d3_rank": d3_display_rank,
            "d3_cutoff_str": d3_info.get("cutoff_str", "—"),
            "d3_delta_str": format_delta(best_sec, d3_cut_sec) if d3_cut_sec else "—",
            "d3_delta_sec": round(best_sec - d3_cut_sec, 2) if d3_cut_sec else None,
            "nationals_invited_str": nat_info.get("invited_prev_str", "—"),
            "nationals_b_cut_str": nat_info.get("b_cut_str", "—"),
            "nationals_delta_str": format_delta(best_sec, nat_cut_sec) if nat_cut_sec else "—",
            "nationals_delta_sec": round(best_sec - nat_cut_sec, 2) if nat_cut_sec else None,
            "is_nationals_invite": is_nationals_invite,
            "is_ncaa_b_cut": is_ncaa_b_cut,
            "is_d3_top": is_d3_top,
            "is_ncac_top": is_ncac_top,
            "is_ncac_a_final": is_ncac_a_final,
            "is_on_bubble": is_on_bubble,
            "is_notable": primary_tier != "OTHER",
            "primary_tier": primary_tier,
            "tier_priority": tier_priority,
            "badges": badges,
        })

    # Sort entries by tier_priority, then ncac_rank, then event_order, then best_time_sec
    evaluated_entries.sort(
        key=lambda x: (
            x["tier_priority"],
            x["ncac_rank"] or 99,
            x["event_order"],
            x["best_time_sec"],
        )
    )

    counts = {
        "total_swims": len(evaluated_entries),
        "notable_swims": sum(1 for e in evaluated_entries if e["is_notable"]),
        "nationals_level": sum(1 for e in evaluated_entries if e["is_nationals_invite"] or e["is_ncaa_b_cut"]),
        "d3_top": sum(1 for e in evaluated_entries if e["is_d3_top"]),
        "ncac_top": sum(1 for e in evaluated_entries if e["is_ncac_top"]),
        "ncac_a_final": sum(1 for e in evaluated_entries if e["is_ncac_a_final"]),
        "on_bubble": sum(1 for e in evaluated_entries if e["is_on_bubble"]),
    }

    return {
        "meet_id": meet_data["meet_id"],
        "meet_name": meet_data["meet_name"],
        "source": meet_data.get("source", ""),
        "is_live_or_active": meet_data.get("is_live_or_active", False),
        "completed_event_files": meet_data.get("completed_event_files", 0),
        "total_event_files": meet_data.get("total_event_files", 0),
        "summary": counts,
        "entries": evaluated_entries,
    }
