# Project: AI Forecaster (paper trading on prediction markets)

## Research question
"Can an AI predict real-world events better than the crowd?" Each day an AI
(Claude) forecasts ~10 Polymarket questions BLIND (it never sees the market
price), and we score it against the crowd on exactly the same questions.

PAPER ONLY: no real money, ever. We only read public market prices.

## About me
I'm fairly new to coding. Explain what you're doing
in plain language, tell me exactly what to click or type when I need to do
something myself, and keep the code simple and well-commented.

## Tech stack
- Python 3, requests, python-dotenv
- Polymarket Gamma API (public, no key) for questions, prices and results
- Google News RSS (free) for research
- Claude API via the Message Batches API (one request per day, half price)
- Discord webhook (optional) for a daily summary
- GitHub Actions for scheduling, GitHub Pages (docs/) for the website
  (same newspaper style as my first project, The Morning Brief)

## Rules
- Never hardcode API keys. .env locally (in .gitignore), GitHub Secrets in Actions.
- Forecasts must be blind: never put market prices, volumes or odds in the
  prompt, and filter news that mentions prediction markets or odds.
- Forecast files in data/forecasts/ are written once and never edited. They
  are committed before questions resolve (the tamper-evident record).
- Settings marked FROZEN in config.py (including the model) must not change
  mid-experiment. If one must, log the date and reason in the README.
- One Claude request per day; keep costs around $1-3 a month.
- Handle errors gracefully: if one source fails, carry on and note it.
- Score honestly: both sides on the same questions, report whatever happens.
- Tests use fake data only (no keys, no internet): `python -m pytest`.
- Every page and message carries the disclaimer: research only, paper
  trading, not financial or betting advice.
