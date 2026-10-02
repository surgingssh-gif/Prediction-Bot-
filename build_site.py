"""
build_site.py - Works out all the scores from the saved records and writes
docs/data.js, which the website (docs/index.html + docs/app.js) reads.

Everything is recomputed from the raw records every time, so the website
can always be checked against the forecast files.

Run it with:  python build_site.py
"""

import json
import os
from datetime import datetime, timezone

import config
import scoring
import storage
import trading

OUTPUT_FILE = os.path.join("docs", "data.js")
DEFAULT_REPO = "surgingssh-gif/Prediction-Bot-"


def _row(day, q, resolutions, pnl_by_id):
    """One question, trimmed to what the website shows (short keys keep the file small)."""
    res = resolutions.get(q["market_id"]) or {}
    forecast = q.get("forecast") or {}
    bet = q.get("bet")
    row = {
        "id": q["market_id"],
        "run": day["run_id"],
        "q": q["question"],
        "topic": q.get("topic"),
        "url": q.get("url"),
        "end": (q.get("end_date") or "")[:10],
        "asked": day.get("created_at"),
        "ai": forecast.get("probability"),
        "crowd": q["snapshot"].get("crowd"),
        "why": forecast.get("reasoning"),
        "news": [
            {"t": h["title"], "s": h.get("source"), "d": h.get("published"), "l": h.get("link")}
            for h in q.get("news") or []
        ],
        "note": q.get("bet_note"),
    }
    if bet:
        row["bet"] = {k: bet[k] for k in ("side", "price", "shares", "cost", "fee", "gap_pts")}
    if q.get("excluded"):
        row["excluded"] = q["excluded"]
    if res:
        row["outcome"] = res["outcome"]
        row["settled"] = res["resolved_at"]
        if row["ai"] is not None and res["outcome"] in (0, 1):
            row["ai_brier"] = round(scoring.brier(row["ai"], res["outcome"]), 4)
            row["crowd_brier"] = round(scoring.brier(row["crowd"], res["outcome"]), 4)
        if q["market_id"] in pnl_by_id:
            row["pnl"] = pnl_by_id[q["market_id"]]
    return row


def daily_bankroll(history, days):
    """The bankroll at the end of each day (for the chart), from the first forecast day on."""
    points = {}
    if days:
        first = days[0].get("forecast_at") or days[0].get("created_at")
        points[first[:10]] = config.STARTING_BANKROLL
    for point in history:
        if point["time"]:
            points[point["time"][:10]] = point["equity"]
    return [{"date": d, "equity": e} for d, e in sorted(points.items())]


def build_data(days, resolutions, pending=None):
    """Everything the website needs, as one dict."""
    pending = pending or []
    rows = scoring.scored_questions(days, resolutions)
    portfolio = trading.replay(days, resolutions)
    pnl_by_id = {s["market_id"]: s["pnl"] for s in portfolio["settled"]}

    all_rows = [_row(d, q, resolutions, pnl_by_id) for d in days for q in d.get("questions", [])]
    open_rows = [r for r in all_rows if "outcome" not in r and r["ai"] is not None and not r.get("excluded")]
    settled_rows = [r for r in all_rows if "outcome" in r]
    settled_rows.sort(key=lambda r: r["settled"], reverse=True)

    settled_bets = portfolio["settled"]
    wins = sum(1 for s in settled_bets if s["pnl"] > 0)
    staked = sum(r["bet"]["cost"] for r in settled_rows if r.get("bet"))
    all_bets = [q["bet"] for d in days for q in d.get("questions", []) if q.get("bet")]
    costs = [d.get("cost_usd") for d in days if d.get("cost_usd") is not None]

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo": os.getenv("GITHUB_REPOSITORY") or DEFAULT_REPO,
        "model": config.MODEL,
        "effort": config.EFFORT,
        "settings": {
            "per_day": config.QUESTIONS_PER_DAY,
            "min_days": config.MIN_DAYS_TO_RESOLVE,
            "max_days": config.MAX_DAYS_TO_RESOLVE,
            "min_volume": config.MIN_VOLUME,
            "min_liquidity": config.MIN_LIQUIDITY,
            "max_spread": config.MAX_SPREAD,
            "min_price": config.MIN_CROWD_PRICE,
            "max_price": config.MAX_CROWD_PRICE,
            "headlines": config.HEADLINES_PER_QUESTION,
            "lookback": config.NEWS_LOOKBACK,
            "start": config.STARTING_BANKROLL,
            "min_edge": config.MIN_EDGE,
            "kelly": config.KELLY_FRACTION,
            "max_bet": config.MAX_BET_FRACTION,
        },
        "stats": scoring.summary(rows),
        "calibration": {"ai": scoring.calibration(rows, "ai"), "crowd": scoring.calibration(rows, "crowd")},
        "topics": scoring.by_topic(rows),
        "running": scoring.running_scores(rows),
        "portfolio": {
            "start": config.STARTING_BANKROLL,
            "equity": portfolio["equity"],
            "cash": portfolio["cash"],
            "open_cost": portfolio["open_cost"],
            "open_bets": len(portfolio["open"]),
            "bets": len(all_bets),
            "settled_bets": len(settled_bets),
            "wins": wins,
            "pnl": round(sum(s["pnl"] for s in settled_bets), 2),
            "staked": round(staked, 2),
            "fees": round(sum(b["fee"] for b in all_bets), 2),
        },
        "bankroll": daily_bankroll(portfolio["history"], days),
        "open": sorted(open_rows, key=lambda r: r["end"]),
        "settled": settled_rows[: config.MAX_SETTLED_ON_PAGE],
        "settled_total": len(settled_rows),
        "runs": [
            {"run": d["run_id"], "asked": d.get("created_at"), "answered": d.get("forecast_at"),
             "n": len(d.get("questions", [])), "cost": d.get("cost_usd"), "error": d.get("error")}
            for d in days
        ],
        "pending": [{"run": d["run_id"], "asked": d.get("created_at"), "n": len(d.get("questions", []))}
                    for d in pending],
        "total_cost": round(sum(costs), 4),
    }


PREFIX = "window.FORECAST_DATA = "


def _same_as_saved(data, path):
    """True if the saved file has the same data (ignoring when it was built)."""
    try:
        with open(path, encoding="utf-8") as f:
            saved = json.loads(f.read().strip()[len(PREFIX):].rstrip(";"))
    except (OSError, ValueError):
        return False
    return {**saved, "generated_at": None} == {**data, "generated_at": None}


def write_data(data, path=OUTPUT_FILE):
    """Writes docs/data.js. Skips it if nothing but the time changed, so the
    repository doesn't get a pointless commit on every run. Returns True if written."""
    if _same_as_saved(data, path):
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(PREFIX)
        # Compact (no spaces) so the file stays small as the months go by.
        json.dump(data, f, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        f.write(";\n")
    return True


def main():
    data = build_data(storage.read_forecasts(), storage.read_resolutions(), storage.read_pending())
    if not write_data(data):
        print(f"{OUTPUT_FILE} is already up to date.")
        return
    print(f"Wrote {OUTPUT_FILE}: {len(data['open'])} open, {data['settled_total']} settled, "
          f"bankroll ${data['portfolio']['equity']:,.2f}.")


if __name__ == "__main__":
    main()
