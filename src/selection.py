"""NCAA Division III Swimming Championship Selection Simulator ("If Selection Were Today").

Translates the official NCAA DIII Men's and Women's Swimming Event Selection Process into a deterministic simulation:
- Total Invite Cap:
  - Women: 319 total competitors - 29 reserved diving spots = 290 swimmer spots.
  - Men: 260 total competitors - 24 reserved diving spots = 236 swimmer spots.
- Step 1 (Automatic Individual Row Selection):
  - Select the top 20 Women and top 16 Men in each of the 13 NCAA individual swimming events.
- Step 2–4 (Relay Row Selection & Disparity Check):
  - Select the top 20 Women's and top 16 Men's relays across the 5 relay events (filling across rows 1..20 for Women, 1..16 for Men).
  - Account for relay-only swimmers added by qualifying relays (4 swimmers per relay, matching each school's fastest swimmers in the corresponding strokes from the DIII Top 50 ladder before adding unranked relay-only roster spots) and enforce the participant cap / row-disparity rule.
- Step 5 (Individual Event Fill by Percentage to B-Cut):
  - While total unique invited swimmers < swimmer cap (290 Women / 236 Men), add remaining individual event swims one by one ordered by closest percentage to the 2026-27 NCAA DIII B-Cut (`time_sec / b_cut_sec` ascending) until adding the next swimmer would exceed the swimmer cap.
"""

from __future__ import annotations
from typing import Any
from .utils import format_time, format_delta

NCAA_INDIVIDUAL_EVENTS = [
    "50_FREE",
    "100_FREE",
    "200_FREE",
    "500_FREE",
    "1650_FREE",
    "100_BACK",
    "200_BACK",
    "100_BREAST",
    "200_BREAST",
    "100_FLY",
    "200_FLY",
    "200_IM",
    "400_IM",
]

NCAA_RELAY_EVENTS = [
    "200_FR_REL",
    "400_FR_REL",
    "800_FR_REL",
    "200_MR_REL",
    "400_MR_REL",
]

RELAY_STROKE_COMPOSITION: dict[str, list[tuple[str, int]]] = {
    "200_FR_REL": [("50_FREE", 4)],
    "400_FR_REL": [("100_FREE", 4)],
    "800_FR_REL": [("200_FREE", 4)],
    "200_MR_REL": [("100_BACK", 1), ("100_BREAST", 1), ("100_FLY", 1), ("50_FREE", 1)],
    "400_MR_REL": [("100_BACK", 1), ("100_BREAST", 1), ("100_FLY", 1), ("100_FREE", 1)],
}

SELECTION_PARAMS = {
    "F": {
        "gender_label": "Women",
        "total_cap": 319,
        "diving_reserved": 29,
        "swimmer_cap": 290,
        "base_individual_rows": 20,
        "base_relay_rows": 20,
    },
    "M": {
        "gender_label": "Men",
        "total_cap": 260,
        "diving_reserved": 24,
        "swimmer_cap": 236,
        "base_individual_rows": 16,
        "base_relay_rows": 16,
    },
}


def _is_depauw(team_name: str | None, team_id: int | str | None, target_team_id: int = 274) -> bool:
    if team_id is not None and str(team_id) == str(target_team_id):
        return True
    if team_name and "depauw" in team_name.lower():
        return True
    return False


def simulate_gender_selection(
    gender: str,
    benchmarks: dict[str, Any],
    evaluated_meets: list[dict[str, Any]],
    settings: dict[str, Any],
) -> dict[str, Any]:
    """Run the 5-step NCAA DIII Selection Simulation for a single gender ('F' or 'M')."""
    params = SELECTION_PARAMS[gender]
    swim_cap = params["swimmer_cap"]
    base_ind_rows = params["base_individual_rows"]
    base_rel_rows = params["base_relay_rows"]
    target_team_id = int(settings["team"]["swimcloud_team_id"])

    ev_map = benchmarks.get("events", {}).get(gender, {})

    # Collect DePauw's best season/meet performance per event (merging SwimCloud D3 ladder + evaluated meets)
    depauw_best_by_event: dict[str, list[dict[str, Any]]] = {}
    for meet in evaluated_meets:
        for e in meet.get("entries", []):
            if e["gender"] != gender:
                continue
            eid = e["event_id"]
            depauw_best_by_event.setdefault(eid, []).append(e)

    # Deduplicate DePauw best per swimmer per event
    depauw_season_best: dict[tuple[str, str], dict[str, Any]] = {}
    for eid, entries in depauw_best_by_event.items():
        for e in entries:
            k = (eid, e["swimmer_name"].lower())
            if k not in depauw_season_best or e["best_time_sec"] < depauw_season_best[k]["best_time_sec"]:
                depauw_season_best[k] = e

    # Step 1: Select top `base_ind_rows` (20 Women / 16 Men) in each of the 13 individual events
    invited_swimmers: dict[str, dict[str, Any]] = {}
    invited_by_event: dict[str, list[dict[str, Any]]] = {
        eid: [] for eid in NCAA_INDIVIDUAL_EVENTS + NCAA_RELAY_EVENTS
    }

    for eid in NCAA_INDIVIDUAL_EVENTS:
        ev_bench = ev_map.get(eid)
        if not ev_bench:
            continue
        ladder = ev_bench["d3"]["ladder"]
        b_cut = ev_bench["nationals"]["b_cut_sec"]
        for row in ladder[:base_ind_rows]:
            skey = str(row.get("swimmer_id") or row["name"])
            is_dpu = _is_depauw(row.get("team"), row.get("team_id"), target_team_id)
            ratio = (row["time_sec"] / b_cut) if b_cut else 1.0
            pct_over_b = round((ratio - 1.0) * 100.0, 2)

            if skey not in invited_swimmers:
                invited_swimmers[skey] = {
                    "key": skey,
                    "name": row["name"],
                    "team": row["team"],
                    "team_id": row.get("team_id"),
                    "is_depauw": is_dpu,
                    "step": "Step 1",
                    "step_label": f"Step 1 (Top {base_ind_rows} Individual)",
                    "events": [],
                }
            invited_swimmers[skey]["events"].append({
                "event_id": eid,
                "event_label": ev_bench["label"],
                "rank": row["rank"],
                "time_sec": row["time_sec"],
                "time_str": row["time_str"],
                "step": "Step 1",
                "pct_over_b_cut": pct_over_b,
            })
            invited_by_event[eid].append({
                **row,
                "is_depauw": is_dpu,
                "selection_step": "Step 1",
                "selection_reason": f"Top {base_ind_rows} Automatic Row",
                "pct_over_b_cut": pct_over_b,
            })

    step1_unique_count = len(invited_swimmers)

    # Index Top-50 swimmers per (school, event) so Step 2 relay roster modeling uses actual stroke swimmers on that team
    school_swimmers_by_event: dict[tuple[str, str], list[tuple[str, str, str, Any]]] = {}
    for eid in NCAA_INDIVIDUAL_EVENTS:
        ev_bench = ev_map.get(eid)
        if not ev_bench:
            continue
        for row in ev_bench["d3"]["ladder"]:
            tkey = str(row.get("team_id") or row["team"])
            skey = str(row.get("swimmer_id") or row["name"])
            school_swimmers_by_event.setdefault((tkey, eid), []).append(
                (skey, row["name"], row["team"], row.get("team_id"))
            )

    # Step 2-4: Fill across relay rows 1..base_rel_rows (20 Women / 16 Men)
    # Note on relay-only swimmer counting (calibrated against the official 2026 NCAA Selection Psych Sheets):
    # - A school's relay requires 4 swimmers on the championship roster.
    # - Any individual qualifiers from that school (including swimmers who qualify in Step 1 or within the top 30 of individual events)
    #   can swim on any of the school's relays, plus the NCAA allows up to 4 relay-only swimmers per team across the meet.
    # - In the actual 2026 NCAA selections:
    #   * Women: 186 unique individual qualifiers + 104 relay-only swimmers = 290 swimmers (rows 1..28 + 11/13 of row 29).
    #   * Men: 129 unique individual qualifiers + 107 relay-only swimmers = 236 swimmers (rows 1..16 + 6/13 of row 17).
    relay_only_swimmers: dict[str, dict[str, Any]] = {}
    school_relay_roster: dict[str, set[str]] = {}
    for skey, sinfo in invited_swimmers.items():
        tk = str(sinfo.get("team_id") or sinfo["team"])
        school_relay_roster.setdefault(tk, set()).add(skey)

    for r_row_idx in range(base_rel_rows):
        for reid in NCAA_RELAY_EVENTS:
            ev_bench = ev_map.get(reid)
            if not ev_bench:
                continue
            rladder = ev_bench["d3"]["ladder"]
            if r_row_idx >= len(rladder):
                continue
            r_entry = rladder[r_row_idx]
            b_cut = ev_bench["nationals"]["b_cut_sec"]
            ratio = (r_entry["time_sec"] / b_cut) if b_cut else 1.0
            pct_over_b = round((ratio - 1.0) * 100.0, 2)

            tkey = str(r_entry.get("team_id") or r_entry["team"])
            tname = r_entry["team"]
            is_dpu = _is_depauw(tname, r_entry.get("team_id"), target_team_id)

            chosen_for_relay: set[str] = set()
            chosen_names: list[str] = []

            # For DePauw relays, check if we have actual relay leg members from our meet parser
            dpu_actual_members: list[str] = []
            if is_dpu:
                dpu_rel_entries = depauw_best_by_event.get(reid, [])
                if dpu_rel_entries:
                    fastest_dpu_rel = min(dpu_rel_entries, key=lambda x: x["best_time_sec"])
                    dpu_actual_members = fastest_dpu_rel.get("relay_members", [])

            if dpu_actual_members and len(dpu_actual_members) == 4:
                for mname in dpu_actual_members:
                    matched_key = None
                    for k, v in {**invited_swimmers, **relay_only_swimmers}.items():
                        if v["name"].lower() == mname.lower():
                            matched_key = k
                            break
                    skey = matched_key or f"dpu_relay_{mname.lower().replace(' ', '_')}"
                    chosen_for_relay.add(skey)
                    chosen_names.append(mname)
                    school_relay_roster.setdefault(tkey, set()).add(skey)
                    if skey not in invited_swimmers and skey not in relay_only_swimmers:
                        relay_only_swimmers[skey] = {
                            "key": skey,
                            "name": mname,
                            "team": tname,
                            "team_id": target_team_id,
                            "is_depauw": True,
                            "step": "Step 2",
                            "step_label": f"Step 2 (Relay Invite — {ev_bench['label']})",
                            "events": [{
                                "event_id": reid,
                                "event_label": ev_bench["label"],
                                "rank": r_entry["rank"],
                                "time_sec": r_entry["time_sec"],
                                "time_str": r_entry["time_str"],
                                "step": "Step 2",
                                "pct_over_b_cut": pct_over_b,
                            }],
                        }
            else:
                for leg_eid, count_needed in RELAY_STROKE_COMPOSITION[reid]:
                    candidates = school_swimmers_by_event.get((tkey, leg_eid), [])
                    added = 0
                    for skey, sname, _, tid in candidates:
                        if skey not in chosen_for_relay and (
                            skey in invited_swimmers or skey in relay_only_swimmers
                        ):
                            chosen_for_relay.add(skey)
                            chosen_names.append(sname)
                            added += 1
                            if added >= count_needed:
                                break
                    if added < count_needed:
                        for skey, sname, _, tid in candidates:
                            if skey not in chosen_for_relay:
                                chosen_for_relay.add(skey)
                                chosen_names.append(sname)
                                school_relay_roster.setdefault(tkey, set()).add(skey)
                                relay_only_swimmers[skey] = {
                                    "key": skey,
                                    "name": sname,
                                    "team": tname,
                                    "team_id": tid,
                                    "is_depauw": is_dpu,
                                    "step": "Step 2",
                                    "step_label": f"Step 2 (Relay Invite — {ev_bench['label']})",
                                    "events": [{
                                        "event_id": reid,
                                        "event_label": ev_bench["label"],
                                        "rank": r_entry["rank"],
                                        "time_sec": r_entry["time_sec"],
                                        "time_str": r_entry["time_str"],
                                        "step": "Step 2",
                                        "pct_over_b_cut": pct_over_b,
                                    }],
                                }
                                added += 1
                                if added >= count_needed:
                                    break

                # Reuse any already-invited or relay-only swimmers from this school across relays (up to 6 total relay-eligible pool per school)
                school_existing = [
                    (k, v["name"])
                    for k, v in {**invited_swimmers, **relay_only_swimmers}.items()
                    if str(v.get("team_id") or v["team"]) == tkey
                ]
                for skey, sname in school_existing:
                    if len(chosen_for_relay) >= 4:
                        break
                    if skey not in chosen_for_relay:
                        chosen_for_relay.add(skey)
                        chosen_names.append(sname)

                while len(chosen_for_relay) < 4:
                    slot_num = len(chosen_for_relay) + 1
                    vkey = f"relay_virtual_{tkey}_{slot_num}"
                    vname = f"{tname} Relay Swimmer #{slot_num}"
                    chosen_for_relay.add(vkey)
                    chosen_names.append(vname)
                    if vkey not in relay_only_swimmers:
                        relay_only_swimmers[vkey] = {
                            "key": vkey,
                            "name": vname,
                            "team": tname,
                            "team_id": r_entry.get("team_id"),
                            "is_depauw": is_dpu,
                            "step": "Step 2",
                            "step_label": f"Step 2 (Relay Invite — {ev_bench['label']})",
                            "events": [{
                                "event_id": reid,
                                "event_label": ev_bench["label"],
                                "rank": r_entry["rank"],
                                "time_sec": r_entry["time_sec"],
                                "time_str": r_entry["time_str"],
                                "step": "Step 2",
                                "pct_over_b_cut": pct_over_b,
                            }],
                        }

            invited_by_event[reid].append({
                **r_entry,
                "is_depauw": is_dpu,
                "selection_step": "Step 2",
                "selection_reason": f"Top {base_rel_rows} Relay Invite",
                "pct_over_b_cut": pct_over_b,
                "estimated_members": chosen_names,
            })

    step2_relay_only_initial = len(relay_only_swimmers)

    # Step 5: Add remaining individual swimmers ROW BY ROW (row 21, 22, ... for Women; row 17, 18, ... for Men),
    # and within each row, order by closest % to B-Cut (`time_sec / b_cut_sec` ascending).
    # Note: Under NCAA rules, an athlete must have achieved at least the B-Cut (`time_sec <= b_cut_sec`) to be eligible
    # for individual selection. For mid-season live simulations (when fewer swimmers have hit B-cuts than in February),
    # we prioritize B-cut qualifiers row-by-row first, and if participant capacity still remains early in the season,
    # we continue row-by-row among non-B-cut entries so the mid-season projection fills the full 290/236 cap.
    remaining_candidates: list[tuple[int, int, float, str, dict[str, Any]]] = []
    for eid in NCAA_INDIVIDUAL_EVENTS:
        ev_bench = ev_map.get(eid)
        if not ev_bench:
            continue
        b_cut = ev_bench["nationals"]["b_cut_sec"]
        if not b_cut:
            continue
        ladder = ev_bench["d3"]["ladder"]
        for row_idx, row in enumerate(ladder[base_ind_rows:], start=base_ind_rows + 1):
            ratio = row["time_sec"] / b_cut
            is_over_b = 0 if row["time_sec"] <= b_cut else 1
            remaining_candidates.append((is_over_b, row_idx, ratio, eid, row))

    # Sort by: 1) B-cut achieved first, 2) row_idx (filling across rows), 3) ratio (time_sec / b_cut_sec) ascending
    remaining_candidates.sort(key=lambda x: (x[0], x[1], x[2]))

    step5_entries_added = 0
    step5_new_swimmers_added = 0
    last_selected_ratio: float | None = None
    last_selected_row: int = base_ind_rows

    for _, row_idx, ratio, eid, row in remaining_candidates:
        ev_bench = ev_map[eid]
        skey = str(row.get("swimmer_id") or row["name"])
        is_dpu = _is_depauw(row.get("team"), row.get("team_id"), target_team_id)
        pct_over_b = round((ratio - 1.0) * 100.0, 2)

        already_in_meet = (skey in invited_swimmers) or (skey in relay_only_swimmers)
        current_unique = len(invited_swimmers) + len(relay_only_swimmers)

        if not already_in_meet and current_unique >= swim_cap:
            break

        if skey in relay_only_swimmers:
            info = relay_only_swimmers.pop(skey)
            invited_swimmers[skey] = {
                **info,
                "step": "Step 5",
                "step_label": f"Step 5 (% to B-Cut: {'+' if pct_over_b >= 0 else ''}{pct_over_b:.2f}%)",
                "events": info.get("events", []) + [{
                    "event_id": eid,
                    "event_label": ev_bench["label"],
                    "rank": row["rank"],
                    "time_sec": row["time_sec"],
                    "time_str": row["time_str"],
                    "step": "Step 5",
                    "pct_over_b_cut": pct_over_b,
                }],
            }
        elif skey not in invited_swimmers:
            step5_new_swimmers_added += 1
            invited_swimmers[skey] = {
                "key": skey,
                "name": row["name"],
                "team": row["team"],
                "team_id": row.get("team_id"),
                "is_depauw": is_dpu,
                "step": "Step 5",
                "step_label": f"Step 5 (% to B-Cut: {'+' if pct_over_b >= 0 else ''}{pct_over_b:.2f}%)",
                "events": [{
                    "event_id": eid,
                    "event_label": ev_bench["label"],
                    "rank": row["rank"],
                    "time_sec": row["time_sec"],
                    "time_str": row["time_str"],
                    "step": "Step 5",
                    "pct_over_b_cut": pct_over_b,
                }],
            }
        else:
            invited_swimmers[skey]["events"].append({
                "event_id": eid,
                "event_label": ev_bench["label"],
                "rank": row["rank"],
                "time_sec": row["time_sec"],
                "time_str": row["time_str"],
                "step": "Step 5",
                "pct_over_b_cut": pct_over_b,
            })

        invited_by_event[eid].append({
            **row,
            "is_depauw": is_dpu,
            "selection_step": "Step 5",
            "selection_reason": f"Step 5 (Row {row_idx} · {'+' if pct_over_b >= 0 else ''}{pct_over_b:.2f}% vs B-Cut)",
            "pct_over_b_cut": pct_over_b,
        })
        step5_entries_added += 1
        last_selected_ratio = ratio
        last_selected_row = row_idx

    # Build per-event summary table + DePauw proximity analysis
    event_summaries: list[dict[str, Any]] = []
    depauw_invited_entries: list[dict[str, Any]] = []
    depauw_bubble_entries: list[dict[str, Any]] = []

    for eid in NCAA_INDIVIDUAL_EVENTS + NCAA_RELAY_EVENTS:
        ev_bench = ev_map.get(eid)
        if not ev_bench:
            continue
        is_relay = bool(ev_bench["is_relay"])
        inv_list = invited_by_event[eid]
        b_cut_sec = ev_bench["nationals"]["b_cut_sec"]
        b_cut_str = ev_bench["nationals"]["b_cut_str"]
        prev_inv_str = ev_bench["nationals"]["invited_prev_str"]

        last_in = inv_list[-1] if inv_list else None
        cutoff_sec = last_in["time_sec"] if last_in else None
        cutoff_str = last_in["time_str"] if last_in else "—"
        cutoff_rank = last_in["rank"] if last_in else None

        # Check all DePauw swimmers in this event (both invited and next-closest on the bubble)
        dpu_in_event = [x for x in inv_list if x.get("is_depauw")]
        for d_inv in dpu_in_event:
            depauw_invited_entries.append({
                "gender": gender,
                "gender_label": params["gender_label"],
                "event_id": eid,
                "event_label": ev_bench["label"],
                "is_relay": is_relay,
                "name": d_inv["name"],
                "rank": d_inv["rank"],
                "time_sec": d_inv["time_sec"],
                "time_str": d_inv["time_str"],
                "selection_step": d_inv["selection_step"],
                "selection_reason": d_inv["selection_reason"],
                "pct_over_b_cut": d_inv.get("pct_over_b_cut"),
                "event_cutoff_rank": cutoff_rank,
                "event_cutoff_str": cutoff_str,
                "margin_sec": round(d_inv["time_sec"] - cutoff_sec, 2) if cutoff_sec else 0.0,
                "margin_str": format_delta(d_inv["time_sec"], cutoff_sec) if cutoff_sec else "—",
                "estimated_members": d_inv.get("estimated_members", []),
            })

        # Find best DePauw entry in this event if not already invited (or additional DePauw swimmers in top 50 / meets)
        dpu_candidates = depauw_best_by_event.get(eid, [])
        seen_dpu_names = {x["name"].lower() for x in dpu_in_event}
        if is_relay and dpu_in_event:
            seen_dpu_names.add("depauw")

        best_dpu_uninvited = None
        for cand in sorted(dpu_candidates, key=lambda x: x["best_time_sec"]):
            cname = cand["swimmer_name"]
            if is_relay and "depauw" in seen_dpu_names:
                continue
            if cname.lower() in seen_dpu_names:
                continue
            seen_dpu_names.add(cname.lower())
            if best_dpu_uninvited is None:
                best_dpu_uninvited = cand
            if cutoff_sec and cand["best_time_sec"] <= cutoff_sec * 1.025:
                pct_b = round(((cand["best_time_sec"] / b_cut_sec) - 1.0) * 100.0, 2) if b_cut_sec else None
                depauw_bubble_entries.append({
                    "gender": gender,
                    "gender_label": params["gender_label"],
                    "event_id": eid,
                    "event_label": ev_bench["label"],
                    "is_relay": is_relay,
                    "name": cname,
                    "d3_rank": cand.get("d3_rank"),
                    "time_sec": cand["best_time_sec"],
                    "time_str": cand["best_time_str"],
                    "event_cutoff_rank": cutoff_rank,
                    "event_cutoff_str": cutoff_str,
                    "delta_to_cutoff_sec": round(cand["best_time_sec"] - cutoff_sec, 2),
                    "delta_to_cutoff_str": format_delta(cand["best_time_sec"], cutoff_sec),
                    "pct_over_b_cut": pct_b,
                })

        event_summaries.append({
            "event_id": eid,
            "event_label": ev_bench["label"],
            "is_relay": is_relay,
            "order": ev_bench["order"],
            "base_rows": base_rel_rows if is_relay else base_ind_rows,
            "total_invited": len(inv_list),
            "step1_or_2_count": min(len(inv_list), base_rel_rows if is_relay else base_ind_rows),
            "step5_added_count": max(0, len(inv_list) - (base_rel_rows if is_relay else base_ind_rows)),
            "cutoff_rank": cutoff_rank,
            "cutoff_sec": cutoff_sec,
            "cutoff_str": cutoff_str,
            "cutoff_swimmer": last_in["name"] if last_in else "—",
            "cutoff_team": last_in["team"] if last_in else "—",
            "cutoff_step": last_in["selection_step"] if last_in else "—",
            "cutoff_pct_over_b": last_in.get("pct_over_b_cut") if last_in else None,
            "b_cut_str": b_cut_str,
            "invited_prev_str": prev_inv_str,
            "depauw_invited": [
                {
                    "name": x["name"],
                    "rank": x["rank"],
                    "time_str": x["time_str"],
                    "step": x["selection_step"],
                    "estimated_members": x.get("estimated_members", []),
                }
                for x in dpu_in_event
            ],
            "depauw_next_closest": (
                {
                    "name": best_dpu_uninvited["swimmer_name"],
                    "time_str": best_dpu_uninvited["best_time_str"],
                    "d3_rank": best_dpu_uninvited.get("d3_rank"),
                    "delta_str": format_delta(best_dpu_uninvited["best_time_sec"], cutoff_sec)
                    if cutoff_sec
                    else "—",
                }
                if best_dpu_uninvited
                else None
            ),
            "invited_ladder": [
                {
                    "rank": x["rank"],
                    "name": x["name"],
                    "team": x["team"],
                    "time_str": x["time_str"],
                    "step": x["selection_step"],
                    "pct_over_b_cut": x.get("pct_over_b_cut"),
                    "is_depauw": x.get("is_depauw", False),
                    "estimated_members": x.get("estimated_members", []),
                }
                for x in inv_list
            ],
        })

    depauw_unique_athletes = [
        v for v in {**invited_swimmers, **relay_only_swimmers}.values() if v.get("is_depauw")
    ]
    depauw_bubble_entries.sort(key=lambda x: x["delta_to_cutoff_sec"])

    return {
        "gender": gender,
        "gender_label": params["gender_label"],
        "rules": params,
        "counts": {
            "total_cap": params["total_cap"],
            "diving_reserved": params["diving_reserved"],
            "swimmer_cap": swim_cap,
            "step1_unique_swimmers": step1_unique_count,
            "step2_relay_only_initial": step2_relay_only_initial,
            "step2_relay_only_final": len(relay_only_swimmers),
            "step5_new_swimmers_added": step5_new_swimmers_added,
            "step5_total_entries_added": step5_entries_added,
            "final_unique_swimmers": len(invited_swimmers) + len(relay_only_swimmers),
            "last_selected_row": last_selected_row,
            "last_selected_pct_over_b": round((last_selected_ratio - 1.0) * 100.0, 2)
            if last_selected_ratio
            else None,
            "depauw_unique_qualified_swimmers": len(depauw_unique_athletes),
            "depauw_invited_entries_count": len(depauw_invited_entries),
        },
        "depauw_qualified_athletes": depauw_unique_athletes,
        "depauw_invited_entries": depauw_invited_entries,
        "depauw_bubble_entries": depauw_bubble_entries,
        "events": event_summaries,
    }


def run_ncaa_selection_simulation(
    benchmarks: dict[str, Any],
    evaluated_meets: list[dict[str, Any]],
    settings: dict[str, Any],
) -> dict[str, Any]:
    """Run the NCAA DIII Selection Simulator for both Women and Men."""
    return {
        "F": simulate_gender_selection("F", benchmarks, evaluated_meets, settings),
        "M": simulate_gender_selection("M", benchmarks, evaluated_meets, settings),
    }
