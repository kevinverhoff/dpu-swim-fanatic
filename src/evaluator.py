"""Evaluate meet swims against:
1. NCAA DIII Rank (highlight Top 24 individual / Top 16 relay, show all the way to Top 50)
2. NCAA B-Cut (2026-27 standard)
3. NCAA Qualifier Line (last year's 2026 Invited Time)
4. NCAC Rank (Top 16 individual / Top 8 relay)
"""

from __future__ import annotations
from typing import Any, Optional
from .utils import format_time, format_delta


def _compute_projected_rank(
    time_sec: float,
    ladder: list[dict[str, Any]],
    swimmer_name: str,
    is_relay: bool,
) -> int:
    """Calculate where `time_sec` ranks (1-indexed) on a deduplicated benchmark ladder."""
    rank = 1
    for entry in ladder:
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
    record prelim/finals history, and classify against NCAA D3 rank, NCAA B-Cut,
    NCAA Qualifier Line, and NCAC rank.
    """
    thresh = settings["thresholds"]
    bubble_pct = float(thresh.get("bubble_pct", 0.015))
    d3_max_rank = int(thresh.get("d3_max_rank", 50))
    event_meta = {ev["id"]: ev for ev in settings["events"]}

    # For relays, find the fastest DePauw relay per (gender, event_id) so only DePauw's top relay per event is ranked against 1-per-school ladders
    fastest_relay_by_event: dict[tuple[str, str], str] = {}
    for sp in meet_data.get("splashes", []):
        if sp.get("is_relay"):
            rk = (sp["gender"], sp["event_id"])
            if rk not in fastest_relay_by_event:
                fastest_relay_by_event[rk] = sp["swimmer_name"]
            else:
                prev_best = min(
                    x["time_sec"]
                    for x in meet_data["splashes"]
                    if x.get("is_relay")
                    and (x["gender"], x["event_id"]) == rk
                    and x["swimmer_name"] == fastest_relay_by_event[rk]
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
        ncac_top_n = int(ev_bench["ncac"]["top_n"])          # 16 indiv / 8 relay
        d3_hi_n = int(ev_bench["d3"]["top_n"])               # 24 indiv / 16 relay
        d3_max_n = int(ev_bench["d3"].get("max_rank", d3_max_rank))  # 50

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
        d3_hi_cut_sec: Optional[float] = d3_info.get("cutoff_sec")
        d3_max_cut_sec: Optional[float] = d3_info.get("max_rank_cutoff_sec")

        ncac_proj_rank = _compute_projected_rank(
            best_sec, ncac_info.get("ladder", []), swimmer_name, is_relay
        )
        d3_proj_rank = _compute_projected_rank(
            best_sec, d3_info.get("ladder", []), swimmer_name, is_relay
        )

        # Achievement flags
        is_nationals_invite = nat_cut_sec is not None and best_sec <= nat_cut_sec
        is_ncaa_b_cut = b_cut_sec is not None and best_sec <= b_cut_sec
        is_ncaa_a_cut = a_cut_sec is not None and best_sec <= a_cut_sec

        # NCAA D3 Highlight (Top 24 Individual / Top 16 Relay) vs Extended (Top 50)
        is_d3_highlight = (
            (d3_hi_cut_sec is not None and best_sec <= d3_hi_cut_sec)
            or (d3_info.get("count_available", 0) < d3_hi_n and d3_proj_rank <= d3_hi_n)
        ) and d3_proj_rank <= d3_hi_n

        is_d3_top50 = (
            (d3_max_cut_sec is not None and best_sec <= d3_max_cut_sec)
            or (d3_info.get("count_available", 0) < d3_max_n and d3_proj_rank <= d3_max_n)
        ) and d3_proj_rank <= d3_max_n

        is_ncac_top = (
            (ncac_cut_sec is not None and best_sec <= ncac_cut_sec)
            or (ncac_info.get("count_available", 0) < ncac_top_n and ncac_proj_rank <= ncac_top_n)
        ) and ncac_proj_rank <= ncac_top_n

        is_ncac_a_final = is_ncac_top and ncac_proj_rank <= 8

        ncac_display_rank = ncac_proj_rank if is_ncac_top else None
        d3_display_rank = d3_proj_rank if is_d3_top50 else None

        # Bubble checks (ordered: NCAA D3 Top 24/16 -> NCAA B-Cut -> NCAA Qualifier Line -> NCAC Top 16/8)
        bubble_targets: list[str] = []
        if not is_d3_highlight and d3_hi_cut_sec is not None:
            if best_sec <= d3_hi_cut_sec * (1.0 + bubble_pct):
                bubble_targets.append(f"DIII Top {d3_hi_n} ({format_delta(best_sec, d3_hi_cut_sec)})")
        if not is_ncaa_b_cut and b_cut_sec is not None:
            if best_sec <= b_cut_sec * (1.0 + bubble_pct):
                bubble_targets.append(f"NCAA B-Cut ({format_delta(best_sec, b_cut_sec)})")
        if not is_nationals_invite and nat_cut_sec is not None:
            if best_sec <= nat_cut_sec * (1.0 + bubble_pct):
                bubble_targets.append(f"NCAA Qualifier Line ({format_delta(best_sec, nat_cut_sec)})")
        if not is_ncac_top and ncac_cut_sec is not None:
            if best_sec <= ncac_cut_sec * (1.0 + bubble_pct):
                bubble_targets.append(f"NCAC Top {ncac_top_n} ({format_delta(best_sec, ncac_cut_sec)})")

        is_on_bubble = len(bubble_targets) > 0

        # Badges ordered strictly:
        # 1. NCAA D3 Rank (Top 24 indiv / Top 16 relay highlighted, or Top 50)
        # 2. NCAA B-Cut (or A-Cut)
        # 3. NCAA Qualifier Line (2026 Invited Time)
        # 4. NCAC Rank (Top 16 indiv / Top 8 relay)
        # 5. Bubble tags
        badges: list[dict[str, str]] = []
        if is_d3_highlight:
            badges.append({
                "id": "d3_highlight",
                "label": f"NCAA DIII #{d3_proj_rank} (Top {d3_hi_n})",
                "tone": "blue",
            })
        elif is_d3_top50:
            badges.append({
                "id": "d3_top50",
                "label": f"NCAA DIII #{d3_proj_rank} (Top 50)",
                "tone": "cyan",
            })

        if is_ncaa_a_cut:
            badges.append({"id": "ncaa_a", "label": "NCAA A-Cut", "tone": "gold"})
        elif is_ncaa_b_cut:
            badges.append({"id": "ncaa_b", "label": "NCAA B-Cut", "tone": "amber"})

        if is_nationals_invite:
            badges.append({"id": "nationals_invite", "label": "NCAA Qualifier Line", "tone": "gold"})

        if is_ncac_top:
            tier_label = (
                f"NCAC #{ncac_proj_rank} (Top 8)"
                if is_ncac_a_final
                else f"NCAC #{ncac_proj_rank} (Top {ncac_top_n})"
            )
            badges.append({
                "id": "ncac_top",
                "label": tier_label,
                "tone": "tiger" if is_ncac_a_final else "green",
            })

        if is_on_bubble:
            for bt in bubble_targets:
                badges.append({"id": "bubble", "label": f"Bubble: {bt}", "tone": "purple"})

        # Primary tier classification
        if is_d3_highlight or is_ncaa_b_cut or is_nationals_invite:
            primary_tier = "D3_HIGHLIGHT"
        elif is_d3_top50:
            primary_tier = "D3_TOP50"
        elif is_ncac_top:
            primary_tier = "NCAC_TOP"
        elif is_on_bubble:
            primary_tier = "BUBBLE"
        else:
            primary_tier = "OTHER"

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
            "d3_rank": d3_display_rank,
            "d3_highlight_n": d3_hi_n,
            "ncac_rank": ncac_display_rank,
            "ncac_top_n": ncac_top_n,
            "nationals_b_cut_str": nat_info.get("b_cut_str", "—"),
            "nationals_b_cut_delta_str": format_delta(best_sec, b_cut_sec) if b_cut_sec else "—",
            "nationals_b_cut_delta_sec": round(best_sec - b_cut_sec, 2) if b_cut_sec else None,
            "nationals_invited_str": nat_info.get("invited_prev_str", "—"),
            "nationals_delta_str": format_delta(best_sec, nat_cut_sec) if nat_cut_sec else "—",
            "nationals_delta_sec": round(best_sec - nat_cut_sec, 2) if nat_cut_sec else None,
            "is_d3_highlight": is_d3_highlight,
            "is_d3_top50": is_d3_top50,
            "is_ncaa_b_cut": is_ncaa_b_cut,
            "is_nationals_invite": is_nationals_invite,
            "is_ncac_top": is_ncac_top,
            "is_ncac_a_final": is_ncac_a_final,
            "is_on_bubble": is_on_bubble,
            "is_notable": primary_tier != "OTHER",
            "primary_tier": primary_tier,
            "badges": badges,
        })

    # Sort Best Performances strictly by:
    # 1. NCAA D3 Rank (Top 24/16 highlighted first, then Top 50 by rank)
    # 2. NCAA B-Cut (achieved first, then closest delta)
    # 3. NCAA Qualifier Line (achieved first, then closest delta)
    # 4. NCAC Rank (1..16)
    # 5. Bubble / Other
    def _best_performance_sort_key(e: dict[str, Any]) -> tuple[Any, ...]:
        return (
            0 if e["is_d3_highlight"] else (1 if e["is_d3_top50"] else 2),
            e["d3_rank"] if e["d3_rank"] is not None else 999,
            0 if e["is_ncaa_b_cut"] else 1,
            0 if e["is_nationals_invite"] else 1,
            0 if e["is_ncac_top"] else (1 if e["is_on_bubble"] else 2),
            e["ncac_rank"] if e["ncac_rank"] is not None else 999,
            e["nationals_b_cut_delta_sec"] if e["nationals_b_cut_delta_sec"] is not None else 999.0,
            e["event_order"],
            e["best_time_sec"],
        )

    evaluated_entries.sort(key=_best_performance_sort_key)

    counts = {
        "total_swims": len(evaluated_entries),
        "notable_swims": sum(1 for e in evaluated_entries if e["is_notable"]),
        "d3_highlight": sum(1 for e in evaluated_entries if e["is_d3_highlight"]),
        "d3_top50": sum(1 for e in evaluated_entries if e["is_d3_top50"]),
        "ncaa_b_cut": sum(1 for e in evaluated_entries if e["is_ncaa_b_cut"]),
        "nationals_invite": sum(1 for e in evaluated_entries if e["is_nationals_invite"]),
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
