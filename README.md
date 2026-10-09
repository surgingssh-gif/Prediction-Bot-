# The Forecaster: Can an AI predict the world better than the crowd?

A research experiment. Every day this bot:

1. Picks about **10 real-world questions** from **Polymarket**, a prediction
   market (economy, politics, tech, business, science, weather, entertainment;
   no sports or crypto), each closing in 1-30 days
2. Searches **Google News** for recent headlines about each one (free)
3. Asks **Claude** for a probability on each, **without showing it the
   market's price**, so it can't copy the crowd (one request per day)
4. Makes **paper bets** (fake money, starting at $1,000) when Claude disagrees
   with the market by 10+ points
5. Checks which questions have settled and **scores both sides**: the AI and
   the crowd, on exactly the same questions
6. Updates a **newspaper-style website** with the scoreboard, a calibration
   chart, open bets and settled results

Every forecast is committed to GitHub with a timestamp **before** its question
resolves, so the record can't be quietly edited afterwards.

> **Research only. Paper trading with fake money: no real bets are placed,
> ever. Nothing here is financial or betting advice.**

---

## How the scoring works (in plain English)

**Brier score** = (forecast − what happened)², averaged over all questions.
"What happened" is 1 for Yes, 0 for No. **Lower is better.**

| Forecast | Happened? | Brier score |
|---|---|---|
| 80% | Yes | (0.8 − 1)² = **0.04** (good) |
| 80% | No | (0.8 − 0)² = **0.64** (bad) |
| 50% | either | **0.25** (the "no idea" score) |

The **crowd's** forecast is the market price when we picked the question (a
62¢ price means 62%). That's the same moment the AI's news was gathered, so
both forecasts are made at the same time. (They don't have the same
information: the market can draw on everything traders know, while the AI
only sees a short news search. That makes the test harder for the AI, not
easier.)

A question only counts once its **deadline** has passed, even if it settled
early. "It happened" results often arrive early, but "it didn't happen" ones
always wait for the deadline, so counting early results would tilt the score.

Questions about the same real-world story (for example, five questions about
one election) are counted as **one story** for the **95% range** of the
difference: if it includes zero, the difference could just be luck. The range
appears once at least 5 separate stories have settled.

**Calibration**: when the AI says 70%, does it happen about 70% of the time?
The calibration chart groups forecasts into buckets to check.

**Paper trading**: the AI buys "Yes" when it thinks the price is too low and
"No" when it's too high, but only when the gap is at least 10 points. It pays
the prices actually on offer in Polymarket's order book (cheapest first,
moving up, and never paying a price that leaves less than a 10-point gap),
plus Polymarket's real fee. Bet size uses the **Kelly
formula** (a classic way to size bets by how big your edge is), scaled down to
a quarter for safety, and never more than 5% of the bankroll on one question.
At most 10% of the available cash goes into new bets each day, so money stays
spread across the whole month of questions instead of the first few days.
And there are never more than 2 open bets on the same real-world story (for
example, the Brazil election), so one surprise can't sink several bets at once.

**Extra measures on the website:**
- **Live prices:** what each open market trades at now, and what the open paper bets are worth at today's prices.
- **Did the crowd move toward the AI?** If market prices keep drifting toward the AI's forecasts after it makes them, that's an early sign it's spotting something, weeks before questions settle.
- **The blend:** a third forecaster, the average of the AI and the crowd. Blends often beat both.
- **Bet breakdown:** paper-bet results by size of disagreement, by YES/NO, and by topic, plus the AI's best and worst calls.

---

## What each file does

| File | What it does |
|---|---|
| `main.py` | The main script. Runs all the steps in order. |
| `config.py` | Every setting in one place (model, filters, bet sizes). |
| `markets.py` | Reads questions, prices and results from Polymarket, and filters them. |
| `news.py` | Searches Google News for each question and drops headlines that leak market odds. |
| `forecaster.py` | Builds the prompt and sends it to Claude through the Batches API. |
| `trading.py` | Paper betting: fees, the Kelly formula, the daily budget and the bankroll. |
| `groups.py` | Spots questions about the same real-world story, so bets don't pile onto one outcome. |
| `resolver.py` | Checks which questions have settled. |
| `scoring.py` | Brier scores, calibration, and the AI-vs-crowd comparison. |
| `storage.py` | Where records are saved (`data/`). |
| `build_site.py` | Works out every score from the records and writes `docs/data.js`. |
| `discord_notify.py` | Optional daily summary in Discord. |
| `docs/` | The website (`index.html`, `app.js`) and its data (`data.js`). |
| `data/forecasts/` | One file per day: questions, prices, news, forecasts, bets. Never edited. |
| `data/pending/` | Questions sent to Claude that it hasn't answered yet. |
| `data/resolutions.json` | Results of settled questions. |
| `data/prices.json` | Each open question's market price, once a day (for live prices and the small price charts). |
| `.github/workflows/daily.yml` | Runs the bot every day on GitHub. |
| `.github/workflows/tests.yml` | Runs the tests whenever code changes. |
| `tests/test_forecaster.py` | Automatic checks with fake data (no keys or internet needed). |

---

## Setup, step by step

### Step 1: Add your Claude key to GitHub

You can reuse your Anthropic account from The Morning Brief, but make a
**new key** for this project. That way you can see each project's costs
separately, and turn one off without breaking the other.

1. Go to https://console.anthropic.com > **Settings** > **API Keys** > **Create Key**.
   Name it `ai-forecaster`. Copy it (it starts with `sk-ant-` and is only shown once).
2. On GitHub, open this repository and click **Settings** (top menu).
3. On the left, click **Secrets and variables** > **Actions**.
4. Click **New repository secret**. Name: `ANTHROPIC_API_KEY`. Secret: paste the key.
   Click **Add secret**.
5. *(Optional)* For Discord messages, make a webhook (in Discord: hover over a
   channel > ⚙️ **Edit Channel** > **Integrations** > **Webhooks** > **New Webhook** >
   **Copy Webhook URL**), then add another secret named `DISCORD_WEBHOOK_URL`.

### Step 2: Let the bot save its records

1. Still in **Settings**, click **Actions** > **General** on the left.
2. Scroll to **Workflow permissions**, choose **Read and write permissions**, click **Save**.

### Step 3: Turn on the website

1. In **Settings**, click **Pages** on the left.
2. Under **Build and deployment** > **Source**, choose **Deploy from a branch**.
3. Under **Branch**, choose `main` and the folder `/docs`, then click **Save**.
4. After a minute or two, refresh. A link appears at the top, like
   `https://surgingssh-gif.github.io/Prediction-Bot-/`. Bookmark it.

### Step 4: Start the experiment

1. Click the **Actions** tab. If GitHub asks, click **I understand my workflows, go ahead and enable them**.
2. Click **Daily forecasts** on the left > **Run workflow** > **Run workflow**.
3. It takes a few minutes (Claude's batch usually finishes in under 10). You'll
   get a green check, a new file in `data/forecasts/`, and an updated website.

From then on it runs by itself every day. GitHub often starts scheduled runs
late or skips some, so there are 5 start times a day (13:07-23:07 UTC). The
first one makes the day's forecasts; the rest just check results.

**About the Run workflow button:** normally it does a regular run (forecasts
if today has none yet, then checks results and refreshes the site). If you tick
**force**, it makes an **extra** round of ~10 new questions even if today's
already exist, saved as e.g. `2026-10-02-2.json` (nothing is ever
overwritten). That costs about the same as a normal day.

### Running it on your own computer (optional)

```bash
pip install -r requirements.txt
cp .env.example .env        # Windows: copy .env.example .env
```

Open `.env` and paste your key. Then:

```bash
python main.py --dry-run    # shows today's questions and exactly what Claude
                            # would see. Free: no Claude call, nothing saved.
python -m pytest            # runs the tests (needs: pip install pytest)
python build_site.py        # rebuilds the website data; then open docs/index.html
```

Avoid running `python main.py` (without `--dry-run`) on your computer once the
experiment is live. It would make real forecasts that only exist on your
computer until you push them.

---

## Cost

Polymarket, Google News, Discord and GitHub are free for this. Claude is the
only paid part: **one request a day**, sent through the Message Batches API at
half price. Expect roughly **$2-3 a month on `claude-opus-5-5`**, or
**$1-1.50 on `claude-sonnet-5-5`**. Each day's exact cost is saved in its
forecast file and shown on the website's Methodology page. You can also check
https://console.anthropic.com > **Usage**.

---

## The experiment's rules (so the results are trustworthy)

- **Blind forecasts.** The prompt never includes prices, volumes or odds.
  Headlines that mention Polymarket, Kalshi, betting, odds, or what traders
  "expect" or have "priced in" are removed, and so are questions that are
  themselves about betting odds.
- **One shot per question.** Each question is forecast once. If Claude's
  request fails, the day is recorded as failed, not retried.
- **No editing.** Forecast files are written once and committed before results
  are known. The record is **tamper-evident**: GitHub's history shows when
  each forecast was made and would show any later change. The daily run
  refuses to save if it would change a saved forecast, and the "Forecast
  guard" check fails if anyone else does.
- **Frozen settings.** Don't change the settings marked FROZEN in
  `config.py` (including the model) during the experiment. If you have to,
  write it in the log below.
- **Report everything**, including results where the AI loses.
- Questions about Anthropic or Claude are skipped (Claude is made by Anthropic,
  so that would be a conflict of interest). This includes events where
  Anthropic is one of the options, like "which company has the best AI model".
- **Phases.** Each day's file records which version of the rules it used
  ("phase"). The website can show results for each phase separately.

### Experiment log

| Date | What changed and why |
|---|---|
| 2026-10-02 | Experiment started with `claude-opus-5-5`, medium effort. |
| 2026-10-03 | Reasoning style in the prompt changed from "a high school student could follow" to "a general reader could follow" (wording only; same rules and output). |
| 2026-10-05 | Added a daily betting budget: at most 10% of available cash goes into new bets each day, with all of that day's bets scaled down equally if needed. Before this, the full $1,000 was tied up in open bets within 4 days, leaving nothing for later questions. Bets placed before this date are unchanged. |
| 2026-10-05 | Added a limit of 2 open bets per real-world story (questions sharing a name like "Brazil" or "Gemini", see `groups.py`). Polymarket splits one story into many events, and 5 bets had piled onto the Brazil election. When the AI wants more, the biggest disagreements get priority. Every question is still forecast and scored; only betting is limited. |
| 2026-10-09 | **Phase 1.1** (Oct 2-8 is Phase 1.0). Changes after a full review: (1) A wider filter for headlines that hint at market odds. Some got through before: "Fed officials wash away market bets on October rate increase" and "Dollar Jumps to 8-Week High on Fed Rate-Hike Bets" (questions 2589812 and 2589813, Oct 2), "Options Traders Give Nvidia a 50% Chance of Hitting $6 Trillion This Month" (5180413, Oct 9) and "...with hike priced in" (3940926, Oct 9). Those forecasts stay in the record, unchanged. (2) Better news searches: dates and filler words are removed from the search, a backup search uses the event title, headlines must name the question's subject, and at most 2 come from one site. The prompt also says when the search failed. (3) Resolution rules can be up to 8,000 characters (was 1,500; `MAX_RULES_CHARS`, FROZEN), and any cut is marked. (4) Paper bets are filled from the real order book instead of assuming every share costs the best price. (5) An exact 10-point gap now counts (a rounding error skipped it). (6) Events where Anthropic is one of the options are skipped: 3554659 (Oct 2), 5178290 (Oct 7) and 3554549 (Oct 9) slipped through before. They stay in the record but shouldn't have been picked. (7) Questions that resolve on betting odds, and derivatives and gaming/streamer markets, are skipped. (8) The daily budget is shared by every run on the same calendar day (UTC), so a late batch can't double it. Scoring: questions count only after their deadline, and the 95% range treats each story as one test (needs 5+ stories). |

---

## Troubleshooting

| Problem | What to check |
|---|---|
| `ANTHROPIC_API_KEY is not set` | Is the secret named exactly `ANTHROPIC_API_KEY`? Locally, is the file named `.env` (not `.env.txt`)? |
| `... credit balance is too low` | Add credit at console.anthropic.com > **Billing**. |
| Run fails at "Save forecasts and website" | Step 2: set **Read and write permissions**. |
| `No questions passed today's filters` | Rare; Polymarket may be quiet. Tomorrow's run tries again. |
| "Claude is still working on..." on the site | The batch took longer than 50 minutes. The next scheduled run collects it. |
| Website not updating | Settings > Pages should show branch `main`, folder `/docs`. |
