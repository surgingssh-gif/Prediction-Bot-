"""
discord_notify.py - Builds a short summary and posts it to Discord through
a webhook (a special link that lets a program post into a channel).
Optional: if DISCORD_WEBHOOK_URL isn't set, the summary is just printed.
"""

import requests

import build_site
import config
import scoring
import storage

DISCORD_LIMIT = 2000  # Discord rejects longer messages


def _money(x):
    """+$12.34 or -$5.00"""
    return f"{'+' if x >= 0 else '-'}${abs(x):,.2f}"


def _pct(p):
    return f"{p * 100:.0f}%"


def build_message(finished_days, newly_settled, resolutions, problems):
    """
    finished_days - forecast days saved this run
    newly_settled - market ids that settled this run
    resolutions   - all results so far
    problems      - anything that went wrong
    """
    lines = ["**🔮 AI Forecaster update**", ""]

    for day in finished_days:
        forecasts = [q for q in day["questions"] if q.get("forecast")]
        bets = [q for q in day["questions"] if q.get("bet")]
        lines.append(f"**New forecasts ({day['run_id']}):** {len(forecasts)} questions, {len(bets)} paper bets")
        for q in bets:
            bet = q["bet"]
            lines.append(
                f"• {q['question']} - AI {_pct(q['forecast']['probability'])} vs market "
                f"{_pct(q['snapshot']['crowd'])} → bought {bet['side']} for ${bet['cost']:.2f}"
            )
        lines.append("")

    if newly_settled:
        lines.append(f"**Settled:** {len(newly_settled)} question(s)")
        days = storage.read_forecasts()
        by_id = {q["market_id"]: q for d in days for q in d.get("questions", [])}
        for market_id in newly_settled:
            q, res = by_id.get(market_id), resolutions[market_id]
            if not q:
                continue
            result = "VOID" if res["outcome"] == "void" else ("YES" if res["outcome"] == 1 else "NO")
            ai = _pct(q["forecast"]["probability"]) if q.get("forecast") else "n/a"
            lines.append(f"• {q['question']} → **{result}** (AI said {ai}, market {_pct(q['snapshot']['crowd'])})")
        lines.append("")

    days = storage.read_forecasts()
    stats = scoring.summary(scoring.scored_questions(days, resolutions))
    # Profit/loss counts open bets at today's market prices, like the website.
    portfolio = build_site.build_data(days, resolutions, prices=storage.read_prices())["portfolio"]
    total = portfolio["marked_equity"] - config.STARTING_BANKROLL
    lines.append(
        f"**Paper P&L: {_money(total)}** (account ${portfolio['marked_equity']:,.2f}; "
        f"{_money(portfolio['pnl'])} settled, {_money(portfolio['unrealized'])} on open bets)"
    )
    if stats["n"]:
        lines.append(
            f"AI vs market ({stats['n']} settled): Brier {stats['ai_brier']:.3f} vs "
            f"{stats['crowd_brier']:.3f} (lower is better)"
        )

    if problems:
        lines.append("")
        lines.append("⚠️ " + " ".join(problems))
    lines.append("")
    lines.append(f"_{config.DISCLAIMER}_")
    return "\n".join(lines)


def split_message(text):
    """Cuts a long message into pieces Discord will accept, at line breaks."""
    chunks, current = [], ""
    for line in text.split("\n"):
        line = line[: DISCORD_LIMIT - 1]
        if len(current) + len(line) + 1 > DISCORD_LIMIT:
            chunks.append(current)
            current = ""
        current += line + "\n"
    if current.strip():
        chunks.append(current)
    return chunks


def send_to_discord(webhook_url, message):
    for chunk in split_message(message):
        response = requests.post(webhook_url, json={"content": chunk}, timeout=30)
        response.raise_for_status()
