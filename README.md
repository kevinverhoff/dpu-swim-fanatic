# DePauw Swim Fanatic (`dpu-swim-fanatic`)

A real-time and seasonal notable swim tracker for **DePauw University Swimming & Diving**. Automatically benchmarks DePauw meet performances (both Prelims and Finals) against:

1. **NCAA DIII Rank** — **Top 24** (Individual events) & **Top 16** (Relays) highlighted, and shown all the way through **Top 50** from SwimCloud's current-season national JSON endpoint.
2. **NCAA B-Cut** — current season NCAA Division III provisional standard.
3. **NCAA Qualifier Line** — last year's official NCAA DIII Invited Time (slowest qualifying time invited to NCAA Nationals).
4. **NCAC Rank** — **Top 16** (Individual events) & **Top 8** (Relays) from SwimCloud's current-season conference JSON endpoint.
5. **On the Bubble** — swims within `1.5%` of any of the above thresholds, showing the exact time drop needed.

---

## Features

- **Dual Ingestion Adapters (Live + SwimCloud JSON)**:
  - **Live Meets (`hytek_realtime`)**: Directly polls Hy-Tek Real-Time Results index/event pages (e.g., `https://sidearmstats.com/kenyon/swim/`) during Prelims and Finals before results ever reach SwimCloud.
  - **Completed Meets (`swimcloud`)**: Pulls official meet splashes via SwimCloud's `/api/splashes/top_times/` JSON endpoint.
  - **Local Override (`data/meets/<meet-id>.json`)**: Supports dropping in local results for meets that only stream on Meet Mobile prior to SwimCloud upload.
- **Fastest-Swim Deduplication with Prelim/Finals Flagging**:
  - Automatically selects each swimmer's fastest time of the meet per event, displays both Prelims and Finals splits (`P: 2:06.61 | F: 2:07.70`), and flags (`⚡`) when a swimmer's fastest time came in Prelims.
- **Low-Compute Smart Gate (`--smart-gate`)**:
  - Designed for GitHub Actions cron polling every 15 minutes on meet weekends: `--smart-gate` checks `config/settings.json` meet dates first and exits in `<50ms` with zero network calls when DePauw does not have an active meet.
- **GitHub Pages Interactive Dashboard (`docs/index.html`) & Markdown Report (`REPORT.md`)**:
  - Filter by meet, Women's/Men's team, highlight tier (Nationals Invite, DIII Top 16, NCAC Top 16, NCAC Top 8 A-Final, On the Bubble), session (Prelims vs. Finals), or search by swimmer/event.
  - Includes a **Season Cutoffs & Benchmarks Table** tab displaying current NCAC #1, NCAC Top 16/8 cutoffs, DIII #1, DIII Top 16/8 cutoffs, and last year's Nationals Invited times.

---

## Quick Start

```bash
# Run pipeline (uses cached SwimCloud benchmarks if <6h old)
python3 run.py

# Force refresh NCAC & NCAA DIII benchmarks from SwimCloud JSON endpoints
python3 run.py --refresh-benchmarks

# Evaluate a specific meet only
python3 run.py --meet 2026-total-performance

# Run with smart date-window gate (exits immediately if no active meet today)
python3 run.py --smart-gate
```

### Viewing the Interactive Dashboard Locally
Open `docs/index.html` directly in any browser (it loads `docs/data/dashboard.js` automatically without needing a local web server), or enable **GitHub Pages** on the repository pointing to the `main` branch `/docs` folder.

---

## Year-Over-Year Season Rollover

All season IDs, NCAA cutoff tables, and tracked meets live in [`config/settings.json`](config/settings.json):
1. Increment `seasons.current_season` (e.g. `"2027-28"`) and `seasons.swimcloud_season_id` (`31`, formula: `start_year - 1996`).
2. Add the new season's block under `ncaa_cutoffs` using the official NCAA DIII Qualifying Standards PDF (which lists the new A-cut, B-cut, and prior year's Invited Time for every event).
3. Add the new season's meet entries under `meets`.
