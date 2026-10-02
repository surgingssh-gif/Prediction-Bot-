"""
forecaster.py - Asks Claude for a probability on each of today's questions.

All of the day's questions go into ONE request, sent through the Message
Batches API. A batch is processed "when there's room" (usually within
minutes, at most 24 hours) and costs half price. Since this is a daily job,
waiting is fine.

The forecast is BLIND: Claude sees the question, its rules and the news,
but never the market price. That way it can't just copy the crowd.
"""

import json
import time
from datetime import datetime, timezone

import anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

import config

SYSTEM_PROMPT = """You are a careful forecaster taking part in a research \
experiment that tests whether an AI can predict real-world events as well as \
prediction markets do. For each question, give the probability that it \
resolves "Yes".

How to forecast well:
- Read the resolution rules closely. The question resolves exactly as the \
rules say, including edge cases, sources and deadlines, not by its headline.
- Start from a base rate (how often things like this happen), then adjust \
for the specific evidence in the news.
- Mind the deadline. Count the days left. Things usually change more slowly \
than headlines suggest, so the status quo often wins over short windows.
- Your training data has a cutoff. Trust the dated headlines provided over \
your memory for anything recent, and don't assume facts you can't see.
- Some questions in a set are related (for example, two candidates in the \
same election). Keep your answers consistent with each other.
- Be calibrated: when you say 70%, it should happen about 7 times in 10. Use \
the full range when the evidence is strong, but avoid 0% and 100%; anything \
can happen.
- You will not be shown any market prices or betting odds, and you should \
not try to guess them. Give your own independent judgment.

For each question, return its id, your probability as a whole-number percent \
from 1 to 99, and 2-4 plain-English sentences of reasoning that a general \
reader could follow, naming the key evidence."""

# The exact JSON shape we want back. The API guarantees Claude's answer
# matches it, so we don't have to guess how to read it.
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "forecasts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "probability_pct": {"type": "integer"},
                    "reasoning": {"type": "string"},
                },
                "required": ["id", "probability_pct", "reasoning"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["forecasts"],
    "additionalProperties": False,
}

MAX_RULES_CHARS = 1500  # very long rules are cut to keep costs down


class ForecastFailed(RuntimeError):
    """Claude's batch finished, but without usable forecasts (it errored,
    expired, declined, or was cut off). Retrying wouldn't be a blind
    first attempt any more, so the day is recorded as failed instead."""


def build_prompt(questions, today):
    """
    Writes the one message that holds all of today's questions. Each gets a
    short id (Q1, Q2...) so the answers can be matched back up.
    Note: no prices, volumes or links to the market are included.
    """
    parts = [f"Today's date is {today}. Here are today's questions.\n"]
    for i, q in enumerate(questions, start=1):
        rules = q["rules"]
        if len(rules) > MAX_RULES_CHARS:
            rules = rules[:MAX_RULES_CHARS] + "..."
        lines = [
            f"=== Q{i} ===",
            f"Question: {q['question']}",
            f"Closes: {(q.get('end_date') or 'unknown')[:10]}",
            f"Resolution rules: {rules}",
            "Recent news:",
        ]
        if q.get("news"):
            for h in q["news"]:
                line = f"- [{h.get('published') or 'undated'}] ({h.get('source') or '?'}) {h['title']}"
                if h.get("summary"):
                    line += f": {h['summary']}"
                lines.append(line)
        else:
            lines.append("- (no news found)")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def make_request(questions, today, custom_id):
    """The batch request for today's questions (one request in the batch)."""
    return Request(
        custom_id=custom_id,
        params=MessageCreateParamsNonStreaming(
            model=config.MODEL,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_prompt(questions, today)}],
            output_config={
                "effort": config.EFFORT,
                "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
            },
        ),
    )


def submit_batch(client, questions, today, custom_id):
    """Sends the batch to Anthropic. Returns the batch id."""
    batch = client.messages.batches.create(requests=[make_request(questions, today, custom_id)])
    return batch.id


def wait_for_batch(client, batch_id, minutes=None, poll_seconds=None):
    """
    Checks every 30 seconds whether the batch is done. Returns True when it
    has finished, or False if we gave up waiting (a later run will check again).
    """
    minutes = config.BATCH_WAIT_MINUTES if minutes is None else minutes
    poll_seconds = poll_seconds or config.BATCH_POLL_SECONDS
    deadline = time.time() + minutes * 60
    while True:
        batch = client.messages.batches.retrieve(batch_id)
        if batch.processing_status == "ended":
            return True
        if time.time() >= deadline:
            return False
        time.sleep(poll_seconds)


def estimate_cost(usage):
    """Dollars for one request, at batch (half) price."""
    prices = config.PRICES_PER_MILLION.get(config.MODEL)
    if not prices or not usage:
        return None
    dollars = (usage["input_tokens"] * prices["input"] + usage["output_tokens"] * prices["output"]) / 1_000_000
    return round(dollars * config.BATCH_DISCOUNT, 4)


def parse_forecasts(text, questions):
    """
    Matches Claude's JSON answer back to the questions. Returns a dict of
    market id -> {"probability": 0.0-1.0, "reasoning": "..."}. Probabilities
    are kept between 1% and 99%. Unknown ids are ignored.
    """
    data = json.loads(text)
    ids = {f"Q{i}": q["market_id"] for i, q in enumerate(questions, start=1)}
    results = {}
    for item in data.get("forecasts", []):
        market_id = ids.get(item["id"].strip().upper())
        if not market_id or market_id in results:
            continue
        pct = min(max(int(item["probability_pct"]), 1), 99)
        results[market_id] = {"probability": pct / 100, "reasoning": item["reasoning"].strip()}
    return results


def collect_results(client, batch_id, questions):
    """
    Reads a finished batch. Returns (forecasts, info) where forecasts is from
    parse_forecasts() and info has the token usage, cost and time.
    Raises ForecastFailed if the batch finished without usable forecasts,
    or another exception if Anthropic couldn't be reached (try again later).
    """
    for result in client.messages.batches.results(batch_id):
        kind = result.result.type
        if kind != "succeeded":
            detail = getattr(getattr(result.result, "error", None), "error", None)
            raise ForecastFailed(f"Claude's batch request {kind}: {detail or 'no details'}")
        message = result.result.message
        if message.stop_reason == "refusal":
            raise ForecastFailed("Claude declined to answer today's questions.")
        if message.stop_reason == "max_tokens":
            raise ForecastFailed("Claude's answer was cut off (hit max_tokens).")
        text = next((block.text for block in message.content if block.type == "text"), "")
        usage = {"input_tokens": message.usage.input_tokens, "output_tokens": message.usage.output_tokens}
        info = {
            "forecast_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "model": message.model,
            "usage": usage,
            "cost_usd": estimate_cost(usage),
        }
        try:
            return parse_forecasts(text, questions), info
        except (ValueError, KeyError, TypeError) as e:
            raise ForecastFailed(f"Couldn't read Claude's answer: {e}")
    raise ForecastFailed("The batch finished but had no results.")


def make_client(api_key):
    return anthropic.Anthropic(api_key=api_key)
