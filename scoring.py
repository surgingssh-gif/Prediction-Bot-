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


def brier(prob, outcome):
    return (prob - outcome) ** 2


def scored_questions(forecast_files, resolutions):
    """
    Every question that has an AI forecast and a real Yes/No result.
    (Cancelled "void" questions don't count.) Returns a list of dicts.
    """
    rows = []
    for day in forecast_files:
        for q in day.get("questions", []):
            res = resolutions.get(q["market_id"])
            forecast = q.get("forecast")
            crowd = q["snapshot"].get("crowd")
            if not res or res["outcome"] not in (0, 1) or not forecast or crowd is None:
                continue
            if q.get("excluded"):
                continue
            ai, outcome = forecast["probability"], res["outcome"]
            rows.append({
                "market_id": q["market_id"],
                "topic": q.get("topic"),
                "resolved_at": res["resolved_at"],
                "ai": ai,
                "crowd": crowd,
                "outcome": outcome,
                "ai_brier": brier(ai, outcome),
                "crowd_brier": brier(crowd, outcome),
            })
    rows.sort(key=lambda r: r["resolved_at"])
    return rows


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
    if n >= 2:
        # Standard error of the average difference (a paired comparison).
        variance = sum((d - mean_diff) ** 2 for d in diffs) / (n - 1)
        margin = 1.96 * math.sqrt(variance / n)
        result["ci_low"] = round(mean_diff - margin, 4)
        result["ci_high"] = round(mean_diff + margin, 4)
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
