"""
trading.py - Paper trading (fake money only). Decides whether to bet on a
question, how much, and keeps track of the bankroll.

How a bet works on a prediction market:
  A "Yes" share pays $1 if the event happens and $0 if not. If it costs
  $0.40, the crowd thinks there's about a 40% chance. If our AI says 60%,
  the share looks cheap, so we buy "Yes". If the AI says 20%, "Yes" looks
  expensive, so we buy "No" instead (a "No" share pays $1 if it DOESN'T happen).

We buy at the price a real trader would pay right now (the best "ask"),
and we pay Polymarket's fee, so the results are realistic.
"""

from datetime import datetime

import config


def fee_per_share(price, rate):
    """
    Polymarket's taker fee for one share: rate x price x (1 - price).
    It's biggest for 50-cent shares and shrinks near 0 or $1.
    """
    return rate * price * (1 - price)


def kelly_fraction(win_prob, cost):
    """
    The Kelly formula: the share of your money to bet to grow it fastest,
    if your probability is right. For a share that costs `cost` (including
    fees) and pays $1:  f = (p - cost) / (1 - cost).
    Returns 0 when the bet isn't worth it.
    """
    if not 0 < cost < 1:
        return 0.0
    return max((win_prob - cost) / (1 - cost), 0.0)


def decide_bet(ai_prob, best_bid, best_ask, fee_rate, equity, cash):
    """
    Decides whether to make a paper bet, and how big.

    ai_prob  - the AI's probability of "Yes" (0-1)
    best_bid - highest price someone will pay for "Yes" right now
    best_ask - lowest price someone will sell "Yes" for right now
    equity   - our total paper money (cash + money in open bets)
    cash     - money not already in a bet

    Returns (bet, note): bet is a dict, or None with a note saying why not.
    """
    if best_bid is None or best_ask is None:
        return None, "No live prices to trade at."

    # Buying "Yes" costs the ask. Buying "No" costs 1 - bid
    # (selling "Yes" at the bid is the same as buying "No").
    yes_gap = ai_prob - best_ask
    no_gap = best_bid - ai_prob
    if yes_gap >= config.MIN_EDGE:
        side, price, win_prob, gap = "YES", best_ask, ai_prob, yes_gap
    elif no_gap >= config.MIN_EDGE:
        side, price, win_prob, gap = "NO", 1 - best_bid, 1 - ai_prob, no_gap
    else:
        biggest = max(yes_gap, no_gap)
        return None, f"Gap of {biggest * 100:.0f} points is under the {config.MIN_EDGE * 100:.0f}-point minimum."

    fee = fee_per_share(price, fee_rate)
    cost = price + fee  # what one share really costs us
    full_kelly = kelly_fraction(win_prob, cost)
    fraction = min(full_kelly * config.KELLY_FRACTION, config.MAX_BET_FRACTION)
    spend = min(fraction * equity, cash)
    if spend < config.MIN_BET:
        return None, f"Bet would be under ${config.MIN_BET:.0f} after fees and limits."

    shares = round(spend / cost, 2)
    return {
        "side": side,
        "price": round(price, 4),
        "shares": shares,
        "stake": round(shares * price, 2),  # money for the shares
        "fee": round(shares * fee, 2),      # Polymarket's fee
        "cost": round(shares * cost, 2),    # stake + fee
        "gap_pts": round(gap * 100, 1),
        "kelly_full": round(full_kelly, 4),
    }, f"Bought {side} ({gap * 100:.0f}-point gap)."


def payout(bet, outcome):
    """
    What a bet pays back when the question settles.
    outcome is 1 (Yes), 0 (No) or "void" (cancelled: each share pays 50 cents).
    """
    if outcome == "void":
        return round(bet["shares"] * 0.5, 2)
    won = (outcome == 1) == (bet["side"] == "YES")
    return round(bet["shares"], 2) if won else 0.0


def _when(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def replay(forecast_files, resolutions, starting=None):
    """
    Rebuilds the paper bankroll from scratch: every bet ever placed (from the
    forecast files) and every result (from resolutions), in time order.

    Recomputing everything each time (instead of saving a running total)
    means the bankroll can always be checked against the raw records.

    Returns a dict with cash, equity, open bets, settled bets and the
    bankroll history (one point per event).
    """
    starting = config.STARTING_BANKROLL if starting is None else starting
    events = []  # (time, order, kind, record)
    for day in forecast_files:
        for q in day.get("questions", []):
            bet = q.get("bet")
            if not bet:
                continue
            opened = _when(day["forecast_at"])
            events.append((opened, 0, "open", q))
            res = resolutions.get(q["market_id"])
            if res:
                # A bet can't settle before it was placed.
                events.append((max(_when(res["resolved_at"]), opened), 1, "settle", q))
    events.sort(key=lambda e: (e[0], e[1]))

    cash = starting
    open_cost = 0.0
    history = [{"time": None, "equity": round(starting, 2)}]
    settled = []
    open_bets = {}
    for when, _, kind, q in events:
        bet = q["bet"]
        if kind == "open":
            cash -= bet["cost"]
            open_cost += bet["cost"]
            open_bets[q["market_id"]] = q
        else:
            outcome = resolutions[q["market_id"]]["outcome"]
            back = payout(bet, outcome)
            cash += back
            open_cost -= bet["cost"]
            open_bets.pop(q["market_id"], None)
            settled.append({"market_id": q["market_id"], "pnl": round(back - bet["cost"], 2), "time": when})
        # Equity counts open bets at what we paid for them (we don't guess
        # what they're worth until they settle).
        history.append({"time": when.strftime("%Y-%m-%dT%H:%M:%SZ"), "equity": round(cash + open_cost, 2)})

    return {
        "cash": round(cash, 2),
        "open_cost": round(open_cost, 2),
        "equity": round(cash + open_cost, 2),
        "open": list(open_bets.values()),
        "settled": settled,
        "history": history,
    }


def daily_budget(cash, spent_today):
    """
    How much more can go into new bets today: a share of the cash we had at
    the start of the day (cash now plus whatever was already bet today),
    minus what was already bet today.
    """
    start_of_day_cash = cash + spent_today
    return max(start_of_day_cash * config.DAILY_BUDGET_FRACTION - spent_today, 0.0)


def fit_to_budget(bets, budget):
    """
    If the day's bets cost more than the budget, shrinks them ALL by the same
    proportion (so no bet is favored just for coming first). Bets that end up
    under the minimum are dropped. Changes the bet dicts in place and
    returns the ones that survive.
    """
    total = sum(b["cost"] for b in bets)
    if total <= budget:
        return bets
    scale = budget / total
    kept = []
    for bet in bets:
        cost_per_share = bet["cost"] / bet["shares"]
        fee_per = bet["fee"] / bet["shares"]
        shares = int(bet["shares"] * scale * 100) / 100  # round down to stay in budget
        if shares * cost_per_share < config.MIN_BET:
            bet["dropped"] = True
            continue
        bet["shares"] = shares
        bet["stake"] = round(shares * bet["price"], 2)
        bet["fee"] = round(shares * fee_per, 2)
        bet["cost"] = round(shares * cost_per_share, 2)
        bet["scaled"] = round(scale, 4)
        kept.append(bet)
    return kept

