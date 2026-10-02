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


def check_resolutions(forecast_files, resolutions, fetch=None):
    """
    Looks up every question that hasn't settled yet. Adds any new results to
    `resolutions` (changing it in place).

    Returns (newly_settled, failures): the market ids that just settled, and
    how many lookups failed (they'll be tried again next run).
    """
    fetch = fetch or markets.fetch_market
    newly_settled, failures = [], 0
    for day in forecast_files:
        for q in day.get("questions", []):
            market_id = q["market_id"]
            # Questions without a forecast (e.g. Claude's request failed)
            # aren't scored, so there's no need to look them up.
            if market_id in resolutions or not q.get("forecast"):
                continue
            try:
                market = fetch(market_id)
            except Exception as e:
                print(f"Couldn't check market {market_id}: {e}")
                failures += 1
                continue
            outcome = markets.resolution(market)
            if outcome is None:
                continue
            resolutions[market_id] = {
                "outcome": outcome,
                "resolved_at": _closed_time(market),
                "question": q["question"],
            }
            newly_settled.append(market_id)
    return newly_settled, failures
