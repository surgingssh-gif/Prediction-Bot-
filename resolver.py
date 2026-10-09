"""
resolver.py - Checks which questions have been settled, and records the
results in data/resolutions.json. Scores and the bankroll are then worked
out from those results by build_site.py.
"""

from datetime import datetime, timezone

import markets


def _closed_time(market):
    """When the market settled, as '2026-10-02T18:46:00Z' (now, if unknown)."""
    text = market.get("closedTime") or ""
    try:
        # Polymarket writes it like "2026-10-02 18:46:00.215694+00".
        text = text.replace(" ", "T")
        if text.endswith("+00"):
            text += ":00"
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def record_price(prices, market_id, market, today):
    """
    Saves the market's current price for the website's live prices and
    sparklines. One point per day: a later run on the same day replaces it.
    """
    crowd = markets.crowd_price(market)
    if crowd is None:
        return
    history = prices.setdefault(market_id, [])
    point = [today, round(crowd, 4)]
    if history and history[-1][0] == today:
        history[-1] = point
    else:
        history.append(point)


def check_resolutions(forecast_files, resolutions, prices=None, fetch=None, today=None):
    """
    Looks up every question that hasn't settled yet. Adds any new results to
    `resolutions` (changing it in place). If `prices` is given, it also
    records each open market's current price there (market id -> list of
    [date, price] points).

    Returns (newly_settled, failures): the market ids that just settled, and
    how many lookups failed (they'll be tried again next run).
    """
    fetch = fetch or markets.fetch_market
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    newly_settled, failures = [], 0
    for day in forecast_files:
        for q in day.get("questions", []):
            market_id = q["market_id"]
            # Questions Claude didn't answer aren't scored, but they're still
            # looked up so the website can show how they turned out.
            if market_id in resolutions:
                continue
            try:
                market = fetch(market_id)
            except Exception as e:
                print(f"Couldn't check market {market_id}: {e}")
                failures += 1
                continue
            outcome = markets.resolution(market)
            if outcome is None:
                # Still open: note today's price (closed markets' prices
                # jump to $0 or $1, which says nothing about the crowd).
                if prices is not None and not market.get("closed"):
                    record_price(prices, market_id, market, today)
                continue
            resolutions[market_id] = {
                "outcome": outcome,
                "resolved_at": _closed_time(market),
                "question": q["question"],
            }
            newly_settled.append(market_id)
    return newly_settled, failures
