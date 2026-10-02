"""
storage.py - Where everything is saved.

data/forecasts/<date>.json  One file per day: the questions, the market
                            prices at that moment, the news Claude read,
                            Claude's forecasts and any paper bets.
                            Written ONCE and never changed afterwards. Each
                            is committed to GitHub with a timestamp before
                            its questions resolve, so the record can't be
                            quietly edited later.
data/pending/<date>.json    Questions sent to Claude whose answers haven't
                            come back yet (deleted once they do).
data/resolutions.json       Results of settled questions, by market id.
data/prices.json            Each open question's market price, once a day
                            (for live prices and sparklines on the website).
"""

import json
import os

FORECASTS_DIR = os.path.join("data", "forecasts")
PENDING_DIR = os.path.join("data", "pending")
RESOLUTIONS_FILE = os.path.join("data", "resolutions.json")
PRICES_FILE = os.path.join("data", "prices.json")


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _read_dir(folder):
    if not os.path.isdir(folder):
        return []
    names = sorted(n for n in os.listdir(folder) if n.endswith(".json"))
    return [read_json(os.path.join(folder, n)) for n in names]


def read_forecasts():
    """Every day's forecast file, oldest first."""
    return _read_dir(FORECASTS_DIR)


def read_pending():
    return _read_dir(PENDING_DIR)


def read_resolutions():
    return read_json(RESOLUTIONS_FILE, {})


def run_ids_for(date_str):
    """Ids of runs already made (or waiting) for a date, e.g. ["2026-10-02"]."""
    ids = []
    for folder in (FORECASTS_DIR, PENDING_DIR):
        if os.path.isdir(folder):
            ids += [n[:-5] for n in os.listdir(folder) if n.startswith(date_str) and n.endswith(".json")]
    return sorted(set(ids))


def new_run_id(date_str):
    """
    "2026-10-02" for the day's first run. A forced extra run on the same day
    gets "2026-10-02-2", then "-3"... so nothing is ever overwritten.
    """
    taken = run_ids_for(date_str)
    if date_str not in taken:
        return date_str
    n = 2
    while f"{date_str}-{n}" in taken:
        n += 1
    return f"{date_str}-{n}"


def save_forecast(day):
    path = os.path.join(FORECASTS_DIR, f"{day['run_id']}.json")
    if os.path.exists(path):
        raise FileExistsError(f"{path} already exists; forecasts are never overwritten.")
    write_json(path, day)


def save_pending(day):
    write_json(os.path.join(PENDING_DIR, f"{day['run_id']}.json"), day)


def delete_pending(run_id):
    path = os.path.join(PENDING_DIR, f"{run_id}.json")
    if os.path.exists(path):
        os.remove(path)


def save_resolutions(resolutions):
    write_json(RESOLUTIONS_FILE, resolutions)


def read_prices():
    return read_json(PRICES_FILE, {})


def save_prices(prices):
    # One line per market keeps this file short and easy to scan.
    os.makedirs(os.path.dirname(PRICES_FILE), exist_ok=True)
    with open(PRICES_FILE, "w", encoding="utf-8") as f:
        f.write("{\n" + ",\n".join(
            f"{json.dumps(k)}:{json.dumps(v, separators=(',', ':'))}" for k, v in sorted(prices.items())
        ) + "\n}\n")


def already_forecast():
    """market id -> event id, for every question ever sent to Claude."""
    seen = {}
    for day in read_forecasts() + read_pending():
        for q in day.get("questions", []):
            seen[q["market_id"]] = q.get("event_id")
    return seen
