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
            blend = (ai + crowd) / 2  # a simple average of the two forecasts
            rows.append({
                "market_id": q["market_id"],
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


def movement(questions):
    """
    Did the crowd move toward the AI after it forecast? For each question,
    compares the market price at forecast time with the latest price we
    recorded while it was still open. "Toward" means the price moved in the
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
