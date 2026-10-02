"""
main.py - The daily AI Forecaster run. Use it like this:

    python main.py            normal run
    python main.py --dry-run  picks today's questions and finds the news, then
                              prints what Claude WOULD be asked (no Claude
                              call, nothing saved, costs nothing)
    python main.py --force    also make a new round of forecasts if today's
                              already exist (saved as e.g. 2026-10-02-2.json)

Each run does these steps:
  1. Collect answers to any earlier batch that was still waiting
  2. Check which questions have settled, record the results, and note
     each open question's current price (for the website)
  3. If today has no forecasts yet: pick ~10 new questions, research
     each one in the news, and send them all to Claude in one batch
  4. When Claude answers: save the forecasts and make paper bets
  5. Post a short summary to Discord (optional)

If one step fails, the others still run, and the problem is noted.
PAPER TRADING ONLY: this program never places real bets.
"""

import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

import config
import forecaster
import markets
import news
import storage
import trading
from discord_notify import build_message, send_to_discord
from resolver import check_resolutions


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def place_bets(day, forecasts, fetch=None):
    """
    Adds Claude's forecasts to the day's questions and decides on paper bets.

    Prices are looked up again right now, because a real trader could only
    trade after the forecast arrived. (The score comparison still uses the
    crowd's price from when the questions were sent, since that's when the
    AI's news was gathered: same information, same moment.)
    """
    fetch = fetch or markets.fetch_market
    portfolio = trading.replay(storage.read_forecasts(), storage.read_resolutions())
    equity, cash = portfolio["equity"], portfolio["cash"]
    for q in day["questions"]:
        q["forecast"] = forecasts.get(q["market_id"])
        q["bet"] = None
        if not q["forecast"]:
            q["bet_note"] = "Claude gave no forecast for this question."
            continue
        try:
            market = fetch(q["market_id"])
            live = markets.snapshot(market)
            if market.get("closed"):
                # It ended before the answer arrived, so it can't count fairly.
                q["excluded"] = "The market closed before the forecast arrived."
                q["bet_note"] = "Market already closed."
                continue
        except Exception as e:
            print(f"Couldn't get live prices for {q['market_id']} ({e}); using the earlier prices.")
            live = q["snapshot"]
        q["trade_snapshot"] = live
        bet, note = trading.decide_bet(
            q["forecast"]["probability"], live["best_bid"], live["best_ask"],
            live["fee_rate"], equity, cash,
        )
        q["bet"], q["bet_note"] = bet, note
        if bet:
            cash -= bet["cost"]
    return day


def finish_batch(client, day, problems, wait_minutes=0):
    """
    Checks a submitted batch. If Claude has answered, saves the day's
    forecasts (and bets) for good and removes the "pending" file.
    Returns the saved day, or None if it's still waiting.
    """
    try:
        if not forecaster.wait_for_batch(client, day["batch_id"], minutes=wait_minutes):
            print(f"Batch for {day['run_id']} is still processing; the next run will check again.")
            return None
        forecasts, info = forecaster.collect_results(client, day["batch_id"], day["questions"])
    except forecaster.ForecastFailed as e:
        # Keep an honest record: the questions are saved with no forecasts
        # and are never retried (a retry wouldn't be a first, blind guess).
        problems.append(f"Claude's forecasts for {day['run_id']} failed: {e}")
        day["forecast_at"] = now_iso()
        day["error"] = str(e)
        for q in day["questions"]:
            q["forecast"], q["bet"] = None, None
    except Exception as e:
        # Couldn't reach Anthropic: leave it pending and try next run.
        problems.append(f"Checking Claude's batch for {day['run_id']} failed: {e}")
        return None
    else:
        day.update(info)
        place_bets(day, forecasts)
    storage.save_forecast(day)
    storage.delete_pending(day["run_id"])
    return day


def start_new_run(client, date_str, problems, dry_run=False):
    """Picks today's questions, researches them and sends them to Claude."""
    events = markets.fetch_events()
    questions = markets.pick_questions(events, storage.already_forecast())
    print(f"Picked {len(questions)} questions from {len(events)} Polymarket events.")
    if not questions:
        problems.append("No questions passed today's filters.")
        return None

    news_failures = 0
    for q in questions:
        try:
            q["news"] = news.fetch_news(q)
        except Exception as e:
            print(f"News search failed for {q['market_id']}: {e}")
            q["news"] = []
            news_failures += 1
    if news_failures:
        problems.append(f"News search failed for {news_failures} of {len(questions)} questions.")

    if dry_run:
        print("\n----- DRY RUN: this is what Claude would see (nothing sent or saved) -----\n")
        print(forecaster.build_prompt(questions, date_str))
        print("\n----- Crowd prices (hidden from Claude) -----")
        for q in questions:
            print(f"{q['snapshot']['crowd'] * 100:5.1f}%  [{q['topic']}] {q['question']}")
        return None

    day = {
        "run_id": storage.new_run_id(date_str),
        "date": date_str,
        "created_at": now_iso(),
        "model": config.MODEL,
        "effort": config.EFFORT,
        "questions": questions,
    }
    day["batch_id"] = forecaster.submit_batch(client, questions, date_str, custom_id=day["run_id"])
    # Saved straight away, so a crash can't lose the batch.
    storage.save_pending(day)
    print(f"Sent {len(questions)} questions to Claude (batch {day['batch_id']}). Waiting...")
    return finish_batch(client, day, problems, wait_minutes=config.BATCH_WAIT_MINUTES)


def main():
    dry_run = "--dry-run" in sys.argv
    force = "--force" in sys.argv

    # Keys come from .env on your computer, or GitHub Secrets on Actions.
    load_dotenv()
    api_key = os.getenv("ANTHROPIC_API_KEY")
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")  # dates are in UTC
    problems = []

    if dry_run:
        start_new_run(None, date_str, problems, dry_run=True)
        for p in problems:
            print(f"Problem: {p}")
        return

    client = forecaster.make_client(api_key) if api_key else None
    if not client:
        problems.append("ANTHROPIC_API_KEY is not set, so no forecasts were made.")

    # --- Step 1: earlier batches that were still waiting ---------------------
    finished = []
    if client:
        for day in storage.read_pending():
            saved = finish_batch(client, day, problems)
            if saved:
                finished.append(saved)

    # --- Step 2: check results ------------------------------------------------
    resolutions = storage.read_resolutions()
    newly_settled = []
    try:
        prices = storage.read_prices()
        newly_settled, failures = check_resolutions(storage.read_forecasts(), resolutions, prices)
        storage.save_resolutions(resolutions)
        storage.save_prices(prices)
        print(f"{len(newly_settled)} question(s) settled since the last run.")
        if failures:
            problems.append(f"Couldn't check {failures} question(s) on Polymarket; will retry next run.")
    except Exception as e:
        problems.append(f"Checking results failed: {e}")

    # --- Step 3: today's new questions ----------------------------------------
    # GitHub starts scheduled runs late (sometimes hours), so the workflow has
    # several start times. The first one makes today's forecasts; the others
    # only do steps 1-2. --force makes an extra round anyway.
    if client and (force or not storage.run_ids_for(date_str)):
        try:
            saved = start_new_run(client, date_str, problems)
            if saved:
                finished.append(saved)
        except Exception as e:
            problems.append(f"Making today's forecasts failed: {e}")
    elif client:
        print(f"Already forecast for {date_str}. (Use --force for an extra round.)")

    # --- Step 4: tell Discord -------------------------------------------------
    for p in problems:
        print(f"Problem: {p}")
    if not (finished or newly_settled or problems):
        return  # nothing new to say
    message = build_message(finished, newly_settled, resolutions, problems)
    if not webhook_url:
        print("\n(DISCORD_WEBHOOK_URL not set, so here's the summary instead.)\n" + message)
        return
    try:
        send_to_discord(webhook_url, message)
    except Exception as e:
        print(f"Sending to Discord failed: {e}\n{message}")


if __name__ == "__main__":
    main()
