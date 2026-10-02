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
both sides had the same information. The site also shows a **95% range** for
the difference: if it includes zero, the difference could just be luck.

**Calibration**: when the AI says 70%, does it happen about 70% of the time?
The calibration chart groups forecasts into buckets to check.

**Paper trading**: the AI buys "Yes" when it thinks the price is too low and
"No" when it's too high, but only when the gap is at least 10 points. It pays
the real asking price and Polymarket's real fee. Bet size uses the **Kelly
formula** (a classic way to size bets by how big your edge is), scaled down to
a quarter for safety, and never more than 5% of the bankroll on one question.

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
| `trading.py` | Paper betting: fees, the Kelly formula, and the bankroll. |
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

**About the Run workflow button:** with **force** ticked (the default), it makes
an **extra** round of ~10 new questions even if today's already exist, saved as
e.g. `2026-10-02-2.json` (nothing is ever overwritten). It costs about the same
as a normal day. To only check results and refresh the site, untick **force**.

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
  Headlines that mention Polymarket, Kalshi, betting or odds are removed.
- **One shot per question.** Each question is forecast once. If Claude's
  request fails, the day is recorded as failed, not retried.
- **No editing.** Forecast files are written once and committed before results
  are known. Their GitHub history proves when each forecast was made.
- **Frozen settings.** Don't change the settings marked FROZEN in
  `config.py` (including the model) during the experiment. If you have to,
  write it in the log below.
- **Report everything**, including results where the AI loses.
- Questions about Anthropic or Claude are skipped (Claude is made by Anthropic,
  so that would be a conflict of interest).

### Experiment log

| Date | What changed and why |
|---|---|
| 2026-10-02 | Experiment started with `claude-opus-5-5`, medium effort. |
| 2026-10-03 | Reasoning style in the prompt changed from "a high school student could follow" to "a general reader could follow" (wording only; same rules and output). |

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
