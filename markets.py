"""
markets.py - Reads public prediction-market questions from Polymarket.

Polymarket's "Gamma" API is free and needs no key. We only READ prices;
nothing here can place a trade.

Words used below:
  event  - a topic, like "Fed decision in October?"
  market - one yes/no question inside an event, like "Will the Fed cut
           rates by 25 bps?" (an event can hold several markets)
  price  - what a "Yes" share costs, from $0 to $1. A price of 0.62 means
           the crowd thinks there's about a 62% chance of "Yes".
"""

import json
import re
from datetime import datetime, timedelta, timezone

import requests

import config

GAMMA_URL = "https://gamma-api.polymarket.com"
# Polymarket blocks requests that don't say who they are.
HEADERS = {"User-Agent": "ai-forecaster-research/1.0 (paper trading only)"}
PAGES = 5        # 5 pages x 100 events = the 500 most-traded events
PAGE_SIZE = 100

# Polymarket tags each event with topics. We map them to our own topics.
# Order matters: the first match wins.
TOPIC_TAGS = {
    "Economy": {"economy", "fed", "fed-rates", "fomc", "inflation", "cpi", "pce", "gdp",
                "jobs", "unemployment", "macro-indicators", "economic-policy",
                "treasuries", "global-rates", "commodities", "oil", "tariffs", "trade"},
    "Tech": {"tech", "ai", "big-tech", "openai", "anthropic", "google", "apple",
             "meta", "ai-releases", "ai-rankings", "spacex"},
    "Business": {"business", "finance", "stocks", "equities", "earnings", "ipo",
                 "companies", "mergers"},
    "Science": {"science", "space", "climate", "health", "medicine", "nasa"},
    "Weather": {"weather", "hurricane", "hurricane-season", "daily-temperature",
                "highest-temperature", "temperature"},
    "Entertainment": {"pop-culture", "culture", "movies", "music", "box-office",
                      "netflix", "top-netflix", "youtube", "awards", "tv",
                      "rotten-tomatoes", "celebrities"},
    "Politics": {"politics", "elections", "global-elections", "world-elections",
                 "geopolitics", "world", "middle-east", "military", "courts",
                 "us-politics", "congress", "trump"},
}

# Anything with one of these tags is skipped, even if it also has a good tag.
SKIP_TAGS = {
    # sports and esports
    "sports", "games", "esports", "soccer", "tennis", "nfl", "nba", "mlb", "nhl",
    "cfb", "ufc", "f1", "formula1", "golf", "cricket", "boxing", "hockey",
    "basketball", "baseball", "counter-strike-2", "league-of-legends", "lol",
    "dota-2", "valorant", "chess",
    # crypto and pure price bets (mostly coin flips on short-term price moves)
    "crypto", "crypto-prices", "bitcoin", "ethereum", "solana", "xrp", "hit-price",
    "finance-updown", "up-or-down", "pyth-finance", "multi-strikes",
    # "Will X say the word Y?" and tweet-count markets
    "mention-markets", "mentions", "tweets-markets",
}


# Claude is made by Anthropic, so it doesn't forecast questions about
# itself or its maker (a conflict of interest).
CONFLICT_WORDS = re.compile(r"\b(anthropic|claude)\b", re.IGNORECASE)


def _parse_json_list(value):
    """Polymarket sends some lists as text, like '["Yes", "No"]'."""
    if isinstance(value, list):
        return value
    try:
        return json.loads(value or "[]")
    except (TypeError, ValueError):
        return []


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_time(text):
    """Turns '2026-10-29T03:59:00Z' into a datetime (or None)."""
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def topic_for(tags):
    """
    Returns our topic name for a list of Polymarket tag slugs, or None if the
    event should be skipped (sports, crypto...) or isn't a topic we cover.
    """
    tags = {t.lower() for t in tags}
    if tags & SKIP_TAGS:
        return None
    for topic, wanted in TOPIC_TAGS.items():
        if tags & wanted:
            return topic
    return None


def crowd_price(market):
    """
    The crowd's probability of "Yes": the middle of the best buy and sell
    prices. Falls back to Polymarket's displayed price if the book is empty.
    """
    bid, ask = _to_float(market.get("bestBid")), _to_float(market.get("bestAsk"))
    if bid is not None and ask is not None and 0 < bid <= ask < 1:
        return round((bid + ask) / 2, 4)
    prices = _parse_json_list(market.get("outcomePrices"))
    return _to_float(prices[0]) if prices else None


def fee_rate(market):
    """Polymarket's taker fee rate for this market (0 if it has no fees)."""
    if not market.get("feesEnabled"):
        return 0.0
    schedule = market.get("feeSchedule") or {}
    return _to_float(schedule.get("rate")) or 0.0


def snapshot(market):
    """The market's prices right now, saved with each forecast."""
    return {
        "time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "crowd": crowd_price(market),
        "best_bid": _to_float(market.get("bestBid")),
        "best_ask": _to_float(market.get("bestAsk")),
        "volume": round(_to_float(market.get("volumeNum") or market.get("volume")) or 0),
        "liquidity": round(_to_float(market.get("liquidityNum") or market.get("liquidity")) or 0),
        "fee_rate": fee_rate(market),
    }


def market_problem(market, now):
    """
    Checks one market against our rules. Returns None if it's good, or a
    short reason why it was skipped (handy for testing and debugging).
    """
    if market.get("closed") or not market.get("active") or not market.get("acceptingOrders", True):
        return "not open for trading"
    if [o.lower() for o in _parse_json_list(market.get("outcomes"))] != ["yes", "no"]:
        return "not a yes/no question"
    end = _parse_time(market.get("endDate"))
    if not end:
        return "no end date"
    days_left = (end - now).total_seconds() / 86400
    if not config.MIN_DAYS_TO_RESOLVE <= days_left <= config.MAX_DAYS_TO_RESOLVE:
        return f"ends in {days_left:.1f} days"
    if (_to_float(market.get("volumeNum") or market.get("volume")) or 0) < config.MIN_VOLUME:
        return "too little volume"
    if (_to_float(market.get("liquidityNum") or market.get("liquidity")) or 0) < config.MIN_LIQUIDITY:
        return "too little liquidity"
    bid, ask = _to_float(market.get("bestBid")), _to_float(market.get("bestAsk"))
    if bid is None or ask is None or ask - bid > config.MAX_SPREAD:
        return "spread too wide"
    price = crowd_price(market)
    if price is None or not config.MIN_CROWD_PRICE <= price <= config.MAX_CROWD_PRICE:
        return "crowd is nearly certain"
    if len(market.get("description") or "") < config.MIN_RULES_LENGTH:
        return "resolution rules too short"
    if CONFLICT_WORDS.search(market.get("question") or ""):
        return "about the AI's own company"
    return None


def fetch_events():
    """
    Downloads the most-traded open events that end in the next 1-30 days.
    If a page fails, we keep the pages we already have.
    """
    now = datetime.now(timezone.utc)
    params = {
        "active": "true",
        "closed": "false",
        "order": "volume24hr",
        "ascending": "false",
        "limit": PAGE_SIZE,
        "end_date_min": (now + timedelta(days=config.MIN_DAYS_TO_RESOLVE)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end_date_max": (now + timedelta(days=config.MAX_DAYS_TO_RESOLVE)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    events = []
    for page in range(PAGES):
        try:
            response = requests.get(f"{GAMMA_URL}/events", params={**params, "offset": page * PAGE_SIZE},
                                    headers=HEADERS, timeout=30)
            response.raise_for_status()
        except requests.RequestException as e:
            if not events:
                raise  # nothing at all - let the caller report it
            print(f"Polymarket page {page + 1} failed ({e}); using the {len(events)} events we have.")
            break
        batch = response.json()
        events += batch
        if len(batch) < PAGE_SIZE:
            break
    return events


def pick_questions(events, already_forecast, count=None, now=None):
    """
    Chooses today's questions from a list of events.

    already_forecast - dict of market id -> event id for every question
                       forecast before (so we never forecast one twice, and
                       don't pile onto one event)
    Returns a list of question dicts, most-traded first.
    """
    count = count or config.QUESTIONS_PER_DAY
    now = now or datetime.now(timezone.utc)
    per_event = {}
    for event_id in already_forecast.values():
        per_event[event_id] = per_event.get(event_id, 0) + 1

    candidates = []
    for event in events:
        topic = topic_for(t.get("slug", "") for t in event.get("tags") or [])
        if not topic:
            continue
        for market in event.get("markets") or []:
            if str(market.get("id")) in already_forecast or market_problem(market, now):
                continue
            candidates.append((event, market, topic))

    # Most-traded today first.
    candidates.sort(key=lambda c: _to_float(c[1].get("volume24hr")) or 0, reverse=True)

    picked, per_topic = [], {}
    for event, market, topic in candidates:
        event_id = str(event.get("id"))
        if per_event.get(event_id, 0) >= config.MAX_PER_EVENT:
            continue
        if per_topic.get(topic, 0) >= config.MAX_PER_TOPIC_PER_DAY:
            continue
        per_event[event_id] = per_event.get(event_id, 0) + 1
        per_topic[topic] = per_topic.get(topic, 0) + 1
        picked.append(make_question(event, market, topic))
        if len(picked) == count:
            break
    return picked


def make_question(event, market, topic):
    """The parts of a market we keep (and save with the forecast)."""
    return {
        "market_id": str(market["id"]),
        "event_id": str(event.get("id")),
        "event_title": event.get("title") or "",
        "option": market.get("groupItemTitle") or "",
        "question": market["question"].strip(),
        "rules": (market.get("description") or "").strip(),
        "topic": topic,
        "end_date": market.get("endDate"),
        "url": f"https://polymarket.com/event/{event.get('slug')}" if event.get("slug") else None,
        "snapshot": snapshot(market),
    }


def fetch_market(market_id):
    """Gets one market's latest details (used to trade and to check results)."""
    response = requests.get(f"{GAMMA_URL}/markets/{market_id}", headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.json()


def resolution(market):
    """
    Has this market been settled? Returns:
      None   - not settled yet (still open, or closed but waiting for the
               official result)
      1 or 0 - settled "Yes" (1) or "No" (0)
      "void" - settled 50/50 (cancelled, or the question was unclear)
    """
    if not market.get("closed"):
        return None
    prices = [_to_float(p) for p in _parse_json_list(market.get("outcomePrices"))]
    if len(prices) != 2 or None in prices:
        return None
    yes, no = prices
    if yes >= 0.99 and no <= 0.01:
        return 1
    if no >= 0.99 and yes <= 0.01:
        return 0
    if abs(yes - 0.5) < 0.01 and abs(no - 0.5) < 0.01:
        return "void"
    return None  # closed, but the final result isn't in yet
