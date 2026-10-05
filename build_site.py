"""
build_site.py - Works out all the scores from the saved records and writes
docs/data.js, which the website (docs/index.html + docs/app.js) reads.

Everything is recomputed from the raw records every time, so the website
can always be checked against the forecast files.

Run it with:  python build_site.py
"""

import json
import os
from datetime import datetime, timedelta, timezone

import config
import scoring
import storage
import trading

OUTPUT_FILE = os.path.join("docs", "data.js")
DEFAULT_REPO = "surgingssh-gif/Prediction-Bot-"


MAX_SPARK_POINTS = 40  # keeps each sparkline (and data.js) small


def _spark(day, q, history):
    """
    The crowd's price over time for one question: the price when the AI
    forecast it, then one point per day after that.
    """
    start = (day.get("created_at") or "")[:10]
    points = [[start, q["snapshot"].get("crowd")]]
    points += [p for p in history if p[0] > start]
    if len(points) > MAX_SPARK_POINTS:
        step = len(points) / MAX_SPARK_POINTS
        points = [points[int(i * step)] for i in range(MAX_SPARK_POINTS - 1)] + [points[-1]]
    return points


def _row(day, q, resolutions, pnl_by_id, prices=None):
    """One question, trimmed to what the website shows (short keys keep the file small)."""
    res = resolutions.get(q["market_id"]) or {}
    history = (prices or {}).get(q["market_id"]) or []
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
        "spark": _spark(day, q, history),
    }
    # The latest price we saw while the market was still open.
    if history and history[-1][0] > (day.get("created_at") or "")[:10]:
        row["latest"] = history[-1][1]
    if bet:
        row["bet"] = {k: bet[k] for k in ("side", "price", "shares", "cost", "fee", "gap_pts")}
        if not res and "latest" in row:
            # What the bet would be worth at today's price (not yet real profit).
            price = row["latest"] if bet["side"] == "YES" else 1 - row["latest"]
            row["bet"]["value"] = round(bet["shares"] * price, 2)
    if q.get("excluded"):
        row["excluded"] = q["excluded"]
    if res:
        row["outcome"] = res["outcome"]
        row["settled"] = res["resolved_at"]
        if row["ai"] is not None and res["outcome"] in (0, 1):
            row["ai_brier"] = round(scoring.brier(row["ai"], res["outcome"]), 4)
            row["crowd_brier"] = round(scoring.brier(row["crowd"], res["outcome"]), 4)
            row["blend_brier"] = round(scoring.brier((row["ai"] + row["crowd"]) / 2, res["outcome"]), 4)
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


def _price_on(history, date):
    """The last recorded price on or before a date (None if there isn't one)."""
    price = None
    for day, value in history:
        if day > date:
            break
        price = value
    return price


def account_history(days, resolutions, prices, today=None):
    """
    The paper account's value at the end of every day: cash plus every open
    bet valued at that day's market price (bets with no price yet count at
    what was paid). This moves every day, unlike the bankroll at cost,
    which only changes when a bet settles.
    """
    bets = []
    for day in days:
        for q in day.get("questions", []):
            if not q.get("bet"):
                continue
            res = resolutions.get(q["market_id"])
            opened = day["forecast_at"][:10]
            settled = max(res["resolved_at"][:10], opened) if res else None
            bets.append((q, opened, settled, res))
    if not bets:
        return []
    start = min(b[1] for b in bets)
    end = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    points = []
    date = datetime.fromisoformat(start)
    while date.strftime("%Y-%m-%d") <= end:
        d = date.strftime("%Y-%m-%d")
        cash, value = config.STARTING_BANKROLL, 0.0
        for q, opened, settled, res in bets:
            if opened > d:
                continue
            bet = q["bet"]
            cash -= bet["cost"]
            if settled and settled <= d:
                cash += trading.payout(bet, res["outcome"])
                continue
            price = _price_on((prices or {}).get(q["market_id"]) or [], d)
            if price is None:
                value += bet["cost"]
            else:
                value += bet["shares"] * (price if bet["side"] == "YES" else 1 - price)
        points.append({"date": d, "value": round(cash + value, 2)})
        date += timedelta(days=1)
    return points


def _short(row):
    """A question in brief, for the best and worst calls lists."""
    keys = ("id", "run", "q", "topic", "url", "ai", "crowd", "outcome", "settled", "ai_brier", "crowd_brier")
    return {k: row[k] for k in keys if k in row}


def build_data(days, resolutions, pending=None, prices=None):
    """Everything the website needs, as one dict."""
    pending = pending or []
    rows = scoring.scored_questions(days, resolutions)
    portfolio = trading.replay(days, resolutions)
    pnl_by_id = {s["market_id"]: s["pnl"] for s in portfolio["settled"]}

    all_rows = [_row(d, q, resolutions, pnl_by_id, prices) for d in days for q in d.get("questions", [])]
    open_rows = [r for r in all_rows if "outcome" not in r and r["ai"] is not None and not r.get("excluded")]
    settled_rows = [r for r in all_rows if "outcome" in r]
    settled_rows.sort(key=lambda r: r["settled"], reverse=True)

    settled_bets = portfolio["settled"]
    wins = sum(1 for s in settled_bets if s["pnl"] > 0)
    staked = sum(r["bet"]["cost"] for r in settled_rows if r.get("bet"))
    all_bets = [q["bet"] for d in days for q in d.get("questions", []) if q.get("bet")]
    costs = [d.get("cost_usd") for d in days if d.get("cost_usd") is not None]

    # Open bets valued at today's prices (bets without a newer price count at cost).
    open_bets = [r["bet"] for r in open_rows if r.get("bet")]
    open_value = sum(b.get("value", b["cost"]) for b in open_bets)
    unrealized = round(open_value - sum(b["cost"] for b in open_bets), 2)

    scored_rows = [r for r in all_rows if "ai_brier" in r and not r.get("excluded")]
    best, worst = scoring.best_and_worst(scored_rows)
    settled_bet_rows = [
        {**r["bet"], "topic": r.get("topic"), "pnl": r["pnl"]} for r in settled_rows if r.get("bet") and "pnl" in r
    ]
    moving = [r for r in all_rows if r["ai"] is not None and not r.get("excluded")]
    latest_run = days[-1]["run_id"] if days else None

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
            "daily_budget": config.DAILY_BUDGET_FRACTION,
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
            "unrealized": unrealized,
            "marked_equity": round(portfolio["cash"] + open_value, 2),
        },
        "movement": scoring.movement(moving),
        "bets": scoring.bet_breakdown(settled_bet_rows),
        "best": [_short(r) for r in best],
        "worst": [_short(r) for r in worst],
        "latest_run": latest_run,
        # The newest run's questions that have already settled (rare, but
        # the "Latest forecasts" section should still list them).
        "latest_settled": [r for r in settled_rows if r["run"] == latest_run and latest_run],
        "bankroll": daily_bankroll(portfolio["history"], days),
        "account": account_history(days, resolutions, prices),
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
    data = build_data(storage.read_forecasts(), storage.read_resolutions(), storage.read_pending(),
                      storage.read_prices())
    if not write_data(data):
        print(f"{OUTPUT_FILE} is already up to date.")
        return
    print(f"Wrote {OUTPUT_FILE}: {len(data['open'])} open, {data['settled_total']} settled, "
          f"bankroll ${data['portfolio']['equity']:,.2f}.")


if __name__ == "__main__":
    main()
