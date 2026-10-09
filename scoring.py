"""
scoring.py - The research part: how good were the AI's forecasts, compared
with the crowd's, on exactly the same questions?

Brier score: (forecast - outcome)^2, averaged over all questions.
  outcome is 1 if it happened, 0 if not. Lower is better.
  0.00 = perfect, 0.25 = always saying 50%, 1.00 = always certain and wrong.
  Example: you said 80% and it happened -> (0.8 - 1)^2 = 0.04 (good).
           you said 80% and it didn't   -> (0.8 - 0)^2 = 0.64 (bad).

The crowd's forecast is the market price at the moment we pulled the
question, which is when the AI got its news, so both had the same
information at the same time.
"""

import math
from datetime import datetime, timedelta, timezone

import groups

# Students' t values for a 95% range, by degrees of freedom. With only a few
# independent stories, the range has to be much wider than the usual 1.96.
T_95 = [(1, 12.71), (2, 4.30), (3, 3.18), (4, 2.78), (5, 2.57), (6, 2.45), (7, 2.36), (8, 2.31),
        (9, 2.26), (10, 2.23), (15, 2.13), (20, 2.09), (30, 2.04), (60, 2.00), (120, 1.98)]
MIN_STORIES_FOR_RANGE = 5   # below this, no "is it luck?" range is shown


def t_value(df):
    """The 95% t value for df degrees of freedom (rounded down to the table)."""
    value = 12.71
    for d, t in T_95:
        if df >= d:
            value = t
    return value if df <= 120 else 1.96


def brier(prob, outcome):
    return (prob - outcome) ** 2


def scored_questions(forecast_files, resolutions, now=None):
    """
    Every question that has an AI forecast and a real Yes/No result.
    (Cancelled "void" questions don't count.) Returns a list of dicts.

    A question only counts once its deadline has passed, even if it settled
    early. Otherwise the early scoreboard would be lopsided: "it happened"
    results often arrive early, while "it didn't happen" ones always wait for
    the deadline.
    """
    now = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = []
    for day in forecast_files:
        for q in day.get("questions", []):
            if (q.get("end_date") or "") > now:
                continue  # settled early; joins the score at its deadline
            res = resolutions.get(q["market_id"])
            forecast = q.get("forecast")
            crowd = q["snapshot"].get("crowd")
            if not res or res["outcome"] not in (0, 1) or not forecast or crowd is None:
                continue
            if q.get("excluded"):
                continue
            ai, outcome = forecast["probability"], res["outcome"]
            blend = (ai + crowd) / 2  # a simple average of the two forecasts
            rows.append({
                "market_id": q["market_id"],
                "event_id": q.get("event_id"),
                "event_title": q.get("event_title"),
                "option": q.get("option"),
                "question": q.get("question"),
                "end_date": q.get("end_date"),
                "phase": day.get("phase", "1.0"),
                "topic": q.get("topic"),
                "resolved_at": res["resolved_at"],
                "ai": ai,
                "crowd": crowd,
                "outcome": outcome,
                "ai_brier": brier(ai, outcome),
                "crowd_brier": brier(crowd, outcome),
                "blend_brier": brier(blend, outcome),
            })
    rows.sort(key=lambda r: r["resolved_at"])
    return rows


def story_ids(rows, days_apart=14):
    """
    Groups rows into real-world "stories": questions from the same Polymarket
    event, or that share a distinctive name (see groups.py) and close within
    about two weeks of each other. Five Brazil-election questions are one
    story, not five separate tests. Returns one story number per row.
    """
    parent = list(range(len(rows)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def close_in_time(a, b):
        try:
            ta = datetime.fromisoformat(a.replace("Z", "+00:00"))
            tb = datetime.fromisoformat(b.replace("Z", "+00:00"))
        except (AttributeError, ValueError):
            return True
        return abs(ta - tb) <= timedelta(days=days_apart)

    for i in range(len(rows)):
        for j in range(i):
            a, b = rows[i], rows[j]
            same_event = a.get("event_id") and a.get("event_id") == b.get("event_id")
            if same_event or (close_in_time(a.get("end_date"), b.get("end_date"))
                              and a.get("question") and b.get("question") and groups.related(a, b)):
                parent[find(i)] = find(j)
    return [find(i) for i in range(len(rows))]


def summary(rows):
    """
    The headline numbers. "diff" is AI minus crowd: below 0 means the AI did
    better. The 95% range (ci_low to ci_high) shows how sure we can be: if it
    includes 0, we can't yet tell the two apart.
    """
    n = len(rows)
    if n == 0:
        return {"n": 0}
    ai = sum(r["ai_brier"] for r in rows) / n
    crowd = sum(r["crowd_brier"] for r in rows) / n
    diffs = [r["ai_brier"] - r["crowd_brier"] for r in rows]
    mean_diff = sum(diffs) / n
    result = {
        "n": n,
        "ai_brier": round(ai, 4),
        "crowd_brier": round(crowd, 4),
        "diff": round(mean_diff, 4),
        "ai_closer": sum(1 for d in diffs if d < 0),
        "crowd_closer": sum(1 for d in diffs if d > 0),
        "ties": sum(1 for d in diffs if d == 0),
        "ci_low": None,
        "ci_high": None,
    }
    if all("blend_brier" in r for r in rows):
        # A third forecaster: the average of the AI and the crowd. Averaging
        # two decent forecasts often beats both of them.
        result["blend_brier"] = round(sum(r["blend_brier"] for r in rows) / n, 4)
    # The 95% range treats each story (not each question) as one independent
    # test: average the difference within each story, then use a t value for
    # the number of stories. Hidden until there are enough stories.
    by_story = {}
    for story, d in zip(story_ids(rows), diffs):
        by_story.setdefault(story, []).append(d)
    story_means = [sum(v) / len(v) for v in by_story.values()]
    k = len(story_means)
    result["stories"] = k
    if k >= MIN_STORIES_FOR_RANGE:
        center = sum(story_means) / k
        variance = sum((m - center) ** 2 for m in story_means) / (k - 1)
        margin = t_value(k - 1) * math.sqrt(variance / k)
        result["ci_low"] = round(center - margin, 4)
        result["ci_high"] = round(center + margin, 4)
    return result


def calibration(rows, key, bins=10):
    """
    Groups forecasts into 10 buckets (0-10%, 10-20%, ...). For each bucket:
    the average forecast and how often those events actually happened.
    A perfectly calibrated forecaster's dots sit on the diagonal line.
    key is "ai" or "crowd".
    """
    buckets = [[] for _ in range(bins)]
    for r in rows:
        index = min(int(r[key] * bins), bins - 1)
        buckets[index].append(r)
    result = []
    for i, items in enumerate(buckets):
        if not items:
            continue
        result.append({
            "bin": i,
            "n": len(items),
            "forecast": round(sum(r[key] for r in items) / len(items), 4),
            "observed": round(sum(r["outcome"] for r in items) / len(items), 4),
        })
    return result


def by_topic(rows):
    """Brier scores split by topic (Economy, Politics...)."""
    topics = {}
    for r in rows:
        topics.setdefault(r["topic"] or "Other", []).append(r)
    return sorted(
        ({"topic": t, **summary(items)} for t, items in topics.items()),
        key=lambda s: -s["n"],
    )


def running_scores(rows):
    """Average Brier score for each side after each settled question (for the chart)."""
    points, ai_total, crowd_total = [], 0.0, 0.0
    for i, r in enumerate(rows, start=1):
        ai_total += r["ai_brier"]
        crowd_total += r["crowd_brier"]
        points.append({"n": i, "date": r["resolved_at"][:10],
                       "ai": round(ai_total / i, 4), "crowd": round(crowd_total / i, 4)})
    return points


def movement(questions):
    """
    Did the crowd move toward the AI after it forecast? For each OPEN
    question, compares the market price at forecast time with the latest
    price recorded. (Settled questions are left out: their last price is
    basically the result, so they'd just repeat the scoreboard.) "Toward" means the price moved in the
    direction the AI said it should. If markets keep drifting toward the
    AI's numbers, that's an early sign it's spotting something real, long
    before the questions settle.

    questions - dicts with "ai", "crowd" (at forecast time) and "latest"
    """
    moves = []
    for q in questions:
        if q.get("latest") is None or q.get("ai") is None or abs(q["ai"] - q["crowd"]) < 0.02:
            continue  # no newer price yet, or the AI basically agreed
        direction = 1 if q["ai"] > q["crowd"] else -1
        moves.append((q["latest"] - q["crowd"]) * direction * 100)
    if not moves:
        return {"n": 0}
    return {
        "n": len(moves),
        "toward": sum(1 for m in moves if m > 0.5),
        "away": sum(1 for m in moves if m < -0.5),
        "avg_pts": round(sum(moves) / len(moves), 2),
    }


def _bet_group(label, bets):
    cost = sum(b["cost"] for b in bets)
    pnl = sum(b["pnl"] for b in bets)
    return {
        "label": label,
        "n": len(bets),
        "wins": sum(1 for b in bets if b["pnl"] > 0),
        "pnl": round(pnl, 2),
        "roi": round(pnl / cost * 100, 1) if cost else None,
    }


def bet_breakdown(settled_bets):
    """
    How the settled paper bets did, split three ways: by how big the
    disagreement was, by YES vs NO, and by topic.

    settled_bets - dicts with "gap_pts", "side", "topic", "cost" and "pnl"
    """
    by_gap = []
    for label, lo, hi in (("10-20 points", 10, 20), ("20-30 points", 20, 30), ("30+ points", 30, 101)):
        group = [b for b in settled_bets if lo <= b["gap_pts"] < hi]
        if group:
            by_gap.append(_bet_group(label, group))
    by_side = [_bet_group(f"Bought {side}", [b for b in settled_bets if b["side"] == side])
               for side in ("YES", "NO") if any(b["side"] == side for b in settled_bets)]
    topics = sorted({b["topic"] or "Other" for b in settled_bets})
    by_topic = [_bet_group(t, [b for b in settled_bets if (b["topic"] or "Other") == t]) for t in topics]
    by_topic.sort(key=lambda g: -g["n"])
    return {"by_gap": by_gap, "by_side": by_side, "by_topic": by_topic}


def best_and_worst(rows, count=5):
    """The questions where the AI beat the crowd by the most, and lost by the most."""
    ranked = sorted(rows, key=lambda r: r["crowd_brier"] - r["ai_brier"], reverse=True)
    best = [r for r in ranked[:count] if r["crowd_brier"] > r["ai_brier"]]
    worst = [r for r in reversed(ranked[-count:]) if r["ai_brier"] > r["crowd_brier"]]
    return best, worst
