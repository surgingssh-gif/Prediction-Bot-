"""
learning.py - The "Learning AI" part (added 2026-10-23, Phase 1.2).

Before each day's forecasts, the AI is shown its own track record: how its
earlier forecasts in this experiment turned out. That way it can notice and
correct its own patterns of mistakes (for example, saying "under 10%" for
things that then happened).

Only the AI's OWN forecasts and the real results are used. Market prices
are never included, so the forecasts stay blind.

The text is saved in each day's forecast file ("track_record"), so the
record shows exactly what the AI was told.
"""

from datetime import datetime, timezone

MIN_SETTLED = 10      # below this, there's too little to learn from
MAX_MISSES = 5        # how many of its worst misses to show

# Forecast ranges for the calibration lines: (low, high, label).
BUCKETS = [
    (0.00, 0.10, "under 10%"),
    (0.10, 0.30, "10-30%"),
    (0.30, 0.70, "30-70%"),
    (0.70, 0.90, "70-90%"),
    (0.90, 1.01, "over 90%"),
]


def settled_forecasts(forecast_files, resolutions, now=None):
    """
    Every past forecast with a real Yes/No result, as (probability, outcome,
    question) tuples. Like the scoreboard, a question only counts once its
    deadline has passed, and cancelled or excluded questions are left out.
    """
    now = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    found = []
    for day in forecast_files:
        for q in day.get("questions", []):
            res = resolutions.get(q["market_id"])
            forecast = q.get("forecast")
            if not forecast or not res or res["outcome"] not in (0, 1) or q.get("excluded"):
                continue
            if (q.get("end_date") or "") > now:
                continue
            found.append((forecast["probability"], res["outcome"], q["question"]))
    return found


def _times(n):
    return "1 time" if n == 1 else f"{n} times"


def track_record(forecast_files, resolutions, now=None):
    """
    A short plain-text summary of the AI's past forecasts and results, to
    put at the top of the prompt. Returns None if too few have settled.
    """
    past = settled_forecasts(forecast_files, resolutions, now)
    n = len(past)
    if n < MIN_SETTLED:
        return None

    avg_said = sum(p for p, _, _ in past) / n
    happened = sum(o for _, o, _ in past) / n
    brier = sum((p - o) ** 2 for p, o, _ in past) / n
    if happened - avg_said > 0.05:
        lean = "So far you have been too low: events happened more often than you said."
    elif avg_said - happened > 0.05:
        lean = "So far you have been too high: events happened less often than you said."
    else:
        lean = "Overall, your average is close to how often things happened."

    lines = [
        "=== Your track record so far ===",
        f"These are your own earlier forecasts in this experiment that have settled ({n} questions). "
        "They show only what you said and what happened (no market information).",
        f"- On average you said {avg_said * 100:.0f}%, and {happened * 100:.0f}% of these events happened. {lean}",
        f"- Your average Brier score is {brier:.3f} (0 is perfect; always saying 50% scores 0.250).",
        "- When you said...",
    ]
    for low, high, label in BUCKETS:
        group = [o for p, o, _ in past if low <= p < high]
        if group:
            lines.append(f"    {label}: it happened {_times(sum(group))} out of {len(group)}.")

    misses = sorted(past, key=lambda x: -((x[0] - x[1]) ** 2))[:MAX_MISSES]
    lines.append("- Your biggest misses:")
    for p, o, question in misses:
        text = question if len(question) <= 120 else question[:117] + "..."
        lines.append(f"    \"{text}\" You said {p * 100:.0f}%; it {'happened' if o else 'did not happen'}.")
    return "\n".join(lines)
