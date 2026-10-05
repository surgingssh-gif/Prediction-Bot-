"""
config.py - Every setting for the experiment, in one place.

IMPORTANT: once the experiment starts, don't change the settings marked
"FROZEN". Changing them halfway would mix two different experiments
together and make the results hard to trust. If you must change one, write
down the date and the reason in the README's "Experiment log".
"""

# ---------------------------------------------------------------------------
# The AI model (FROZEN)
# ---------------------------------------------------------------------------
# The same model is used for the whole experiment, so every forecast is
# comparable. Choices (prices per million tokens, before the 50% batch discount):
#   "claude-opus-5-5"   - best quality,  $4 in / $20 out  (roughly $2-3 a month here)
#   "claude-sonnet-5-5" - cheaper,       $2 in / $10 out  (roughly $1-1.50 a month here)
MODEL = "claude-opus-5-5"

# How hard Claude thinks before answering ("low", "medium", "high").
# "medium" is a good balance of quality and cost for this job. (FROZEN)
EFFORT = "medium"

# Price per million tokens for each model, used to log what each day cost.
# The Message Batches API charges half of these.
PRICES_PER_MILLION = {
    "claude-opus-5-5": {"input": 4.00, "output": 20.00},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00},
}
BATCH_DISCOUNT = 0.5

# ---------------------------------------------------------------------------
# Picking questions (FROZEN)
# ---------------------------------------------------------------------------
QUESTIONS_PER_DAY = 10
MIN_DAYS_TO_RESOLVE = 1     # skip questions ending in less than 1 day
MAX_DAYS_TO_RESOLVE = 30    # ...or more than 30 days away
MIN_VOLUME = 10_000         # total $ traded so far (shows people care)
MIN_LIQUIDITY = 2_000       # $ waiting in the order book (prices are meaningful)
MAX_SPREAD = 0.05           # gap between best buy and sell price (5 cents)
# Skip near-certain questions: the crowd says under 5% or over 95%.
# There's little to learn from them, and both sides would score well.
MIN_CROWD_PRICE = 0.05
MAX_CROWD_PRICE = 0.95
MIN_RULES_LENGTH = 100      # resolution rules shorter than this are too vague
MAX_PER_EVENT = 2           # e.g. at most 2 candidates from one election, ever
MAX_PER_TOPIC_PER_DAY = 3   # keeps each day's questions varied

# ---------------------------------------------------------------------------
# Research (FROZEN)
# ---------------------------------------------------------------------------
HEADLINES_PER_QUESTION = 6
NEWS_LOOKBACK = "14d"       # Google News "when:" filter: only the last 14 days

# ---------------------------------------------------------------------------
# Paper trading (FROZEN) - no real money, ever
# ---------------------------------------------------------------------------
STARTING_BANKROLL = 1000.00
MIN_EDGE = 0.10             # bet only if the AI disagrees with the price by 10+ points
KELLY_FRACTION = 0.25       # bet a quarter of what the Kelly formula says (safer)
MAX_BET_FRACTION = 0.05     # never put more than 5% of the bankroll on one question
MIN_BET = 1.00              # skip bets smaller than $1
# At most this share of the available cash goes into new bets each day
# (added 2026-10-05; see the README's experiment log). Without it, the
# whole bankroll was tied up within 4 days and no new bets could be made.
DAILY_BUDGET_FRACTION = 0.10

# ---------------------------------------------------------------------------
# Running the job
# ---------------------------------------------------------------------------
# How long one run waits for Claude's batch to finish before saving it as
# "pending" for the next run to pick up. Most finish in a few minutes.
BATCH_WAIT_MINUTES = 50
BATCH_POLL_SECONDS = 30

# How many settled questions to list on the website (all of them still
# count in the scores; this only keeps docs/data.js small).
MAX_SETTLED_ON_PAGE = 300

DISCLAIMER = "Research only. Paper trading with fake money. Not financial or betting advice."
