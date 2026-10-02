"""
Tests that run WITHOUT any API keys or internet. They swap the real
Polymarket / Google News / Claude / Discord calls for fake ones.

Run them with:  python -m pytest
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

# Let the tests import main.py, markets.py, etc. from the project folder.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import build_site
import config
import discord_notify
import forecaster
import main
import markets
import news
import scoring
import storage
import trading
from resolver import check_resolutions, record_price

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Fake data
# ---------------------------------------------------------------------------

def fake_market(market_id="1", days=10, bid=0.40, ask=0.42, volume=50_000, **extra):
    market = {
        "id": market_id,
        "question": f"Will thing {market_id} happen?",
        "description": "This market resolves Yes if thing happens by the date, per official sources. " * 3,
        "outcomes": '["Yes", "No"]',
        "outcomePrices": f'["{(bid + ask) / 2}", "{1 - (bid + ask) / 2}"]',
        "endDate": (NOW + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "active": True,
        "closed": False,
        "acceptingOrders": True,
        "volumeNum": volume,
        "liquidityNum": 10_000,
        "volume24hr": volume / 10,
        "bestBid": bid,
        "bestAsk": ask,
        "feesEnabled": True,
        "feeSchedule": {"rate": 0.04},
    }
    market.update(extra)
    return market


def fake_event(event_id="e1", tags=("politics",), markets_list=None, title="Some event"):
    return {
        "id": event_id,
        "title": title,
        "slug": f"event-{event_id}",
        "tags": [{"slug": t} for t in tags],
        "markets": markets_list if markets_list is not None else [fake_market()],
    }


def fake_question(market_id="1", crowd=0.40, topic="Politics"):
    q = markets.make_question(fake_event(), fake_market(market_id), topic)
    q["snapshot"]["crowd"] = crowd
    q["news"] = [{"title": "Big news", "source": "Reuters", "published": "2026-10-01", "summary": "", "link": "x"}]
    return q


def fake_day(run_id, questions, forecast_at="2026-10-02T13:00:00Z"):
    return {"run_id": run_id, "date": run_id[:10], "created_at": "2026-10-02T12:00:00Z",
            "forecast_at": forecast_at, "model": config.MODEL, "questions": questions}


# ---------------------------------------------------------------------------
# Picking questions
# ---------------------------------------------------------------------------

def test_topics_skip_sports_and_crypto():
    assert markets.topic_for(["politics", "elections"]) == "Politics"
    assert markets.topic_for(["economy", "fed-rates"]) == "Economy"
    assert markets.topic_for(["sports", "politics"]) is None      # skip wins
    assert markets.topic_for(["crypto", "economy"]) is None
    assert markets.topic_for(["random-unknown-tag"]) is None


@pytest.mark.parametrize("change, reason", [
    ({"days": 0.5}, "ends in"),
    ({"days": 45}, "ends in"),
    ({"volume": 500}, "too little volume"),
    ({"bid": 0.97, "ask": 0.98}, "nearly certain"),
    ({"bid": 0.30, "ask": 0.50}, "spread"),
    ({"description": "Short."}, "too short"),
    ({"closed": True}, "not open"),
    ({"outcomes": '["Lula", "Bolsonaro"]'}, "yes/no"),
    ({"question": "Will Anthropic have the best AI model?"}, "own company"),
])
def test_market_filters(change, reason):
    assert markets.market_problem(fake_market(), NOW) is None
    assert reason in markets.market_problem(fake_market(**change), NOW)


def test_pick_questions_respects_caps_and_history():
    events = [
        fake_event("e1", ["politics"], [fake_market(str(i)) for i in range(1, 5)]),   # 4 markets in one event
        fake_event("e2", ["economy"], [fake_market("10")]),
        fake_event("e3", ["sports"], [fake_market("20")]),                            # skipped
    ]
    picked = markets.pick_questions(events, already_forecast={"1": "e1"}, now=NOW)
    ids = [q["market_id"] for q in picked]
    assert "1" not in ids          # forecast before
    assert "20" not in ids         # sports
    assert sum(1 for q in picked if q["event_id"] == "e1") == config.MAX_PER_EVENT - 1  # one already used
    assert "10" in ids


def test_crowd_price_is_midpoint():
    assert markets.crowd_price(fake_market(bid=0.40, ask=0.44)) == 0.42


@pytest.mark.parametrize("prices, closed, expected", [
    ('["1", "0"]', True, 1),
    ('["0", "1"]', True, 0),
    ('["0.5", "0.5"]', True, "void"),
    ('["0.7", "0.3"]', True, None),    # closed but not final yet
    ('["1", "0"]', False, None),       # still open
])
def test_resolution(prices, closed, expected):
    assert markets.resolution({"closed": closed, "outcomePrices": prices}) == expected


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------

RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Fed holds rates steady - Reuters</title><source>Reuters</source>
<pubDate>Thu, 01 Oct 2026 13:00:00 GMT</pubDate><link>https://a</link>
<description>&lt;a href="x"&gt;Fed holds rates steady&lt;/a&gt;</description></item>
<item><title>Polymarket traders bet on a cut - CoinDesk</title><source>CoinDesk</source>
<pubDate>Thu, 01 Oct 2026 12:00:00 GMT</pubDate><link>https://b</link></item>
<item><title>Rate hike odds slip to 40% - CNBC</title><source>CNBC</source><link>https://c</link></item>
<item><title>Traders flip to a hold - Kalshi News</title><source>Kalshi News</source><link>https://d</link></item>
<item><title>Jobs report surprises - AP</title><source>AP</source><link>https://e</link></item>
</channel></rss>"""


def test_news_drops_headlines_that_leak_market_prices():
    headlines = news.parse_rss(RSS, limit=10)
    titles = [h["title"] for h in headlines]
    assert titles == ["Fed holds rates steady", "Jobs report surprises"]
    assert headlines[0]["source"] == "Reuters"
    assert headlines[0]["published"] == "2026-10-01"
    assert headlines[0]["summary"] == ""  # it only repeated the title


def test_news_query_is_short_and_uses_the_option():
    q = {"question": "Will the Fed cut rates after the October 2026 meeting?", "option": "", "event_title": ""}
    assert news.build_query(q) == "Fed cut rates October 2026 meeting"
    q2 = {"question": "Will Lula win?", "option": "Lula", "event_title": "Brazil Presidential Election"}
    assert news.build_query(q2) == "Brazil Presidential Election Lula"


# ---------------------------------------------------------------------------
# Claude (faked)
# ---------------------------------------------------------------------------

def test_prompt_never_shows_the_market_price():
    q = fake_question(crowd=0.4321)
    q["snapshot"].update(best_bid=0.4211, best_ask=0.4433)
    prompt = forecaster.build_prompt([q], "2026-10-02")
    for secret in ("0.4321", "43.21", "0.4211", "0.4433", "43%", "polymarket.com"):
        assert secret not in prompt
    assert "Q1" in prompt and q["question"] in prompt and "Big news" in prompt


def test_parse_forecasts_clamps_and_matches_ids():
    questions = [fake_question("a"), fake_question("b")]
    text = json.dumps({"forecasts": [
        {"id": "Q1", "probability_pct": 100, "reasoning": "Sure thing."},
        {"id": "q2", "probability_pct": 0, "reasoning": "No way."},
        {"id": "Q9", "probability_pct": 50, "reasoning": "Unknown id."},
    ]})
    result = forecaster.parse_forecasts(text, questions)
    assert result == {"a": {"probability": 0.99, "reasoning": "Sure thing."},
                      "b": {"probability": 0.01, "reasoning": "No way."}}


class FakeBatches:
    """Stands in for client.messages.batches."""

    def __init__(self, answer=None, stop_reason="end_turn", status="ended", kind="succeeded"):
        self.answer, self.stop_reason, self.status, self.kind = answer, stop_reason, status, kind
        self.created = []

    def create(self, requests):
        self.created.append(requests)
        return SimpleNamespace(id=f"batch_{len(self.created)}")

    def retrieve(self, batch_id):
        return SimpleNamespace(processing_status=self.status)

    def results(self, batch_id):
        message = SimpleNamespace(
            stop_reason=self.stop_reason,
            model=config.MODEL,
            content=[SimpleNamespace(type="text", text=json.dumps(self.answer or {"forecasts": []}))],
            usage=SimpleNamespace(input_tokens=8000, output_tokens=5000),
        )
        yield SimpleNamespace(custom_id="x", result=SimpleNamespace(type=self.kind, message=message))


def fake_client(**kwargs):
    return SimpleNamespace(messages=SimpleNamespace(batches=FakeBatches(**kwargs)))


def test_collect_results_reads_answers_and_cost():
    questions = [fake_question("a")]
    client = fake_client(answer={"forecasts": [{"id": "Q1", "probability_pct": 70, "reasoning": "R"}]})
    forecasts, info = forecaster.collect_results(client, "batch_1", questions)
    assert forecasts["a"]["probability"] == 0.70
    assert info["usage"] == {"input_tokens": 8000, "output_tokens": 5000}
    assert info["cost_usd"] > 0


def test_collect_results_reports_refusal():
    with pytest.raises(forecaster.ForecastFailed, match="declined"):
        forecaster.collect_results(fake_client(stop_reason="refusal"), "b", [fake_question()])


def test_request_uses_frozen_model_and_json_schema():
    request = forecaster.make_request([fake_question()], "2026-10-02", "2026-10-02")
    assert request["params"]["model"] == config.MODEL
    assert request["params"]["output_config"]["format"]["type"] == "json_schema"


# ---------------------------------------------------------------------------
# Paper trading
# ---------------------------------------------------------------------------

def test_fee_matches_polymarket_table():
    # Polymarket's docs: 100 shares at $0.50 with a 0.07 rate cost $1.75 in fees.
    assert round(100 * trading.fee_per_share(0.50, 0.07), 2) == 1.75
    assert round(100 * trading.fee_per_share(0.10, 0.07), 2) == 0.63


def test_kelly():
    assert trading.kelly_fraction(0.6, 0.5) == pytest.approx(0.2)
    assert trading.kelly_fraction(0.4, 0.5) == 0.0


def test_bet_yes_when_ai_is_higher():
    bet, note = trading.decide_bet(0.70, 0.48, 0.50, 0.04, equity=1000, cash=1000)
    assert bet["side"] == "YES" and bet["price"] == 0.50
    assert bet["cost"] <= 1000 * config.MAX_BET_FRACTION + 0.01   # capped at 5%
    assert bet["cost"] == pytest.approx(bet["stake"] + bet["fee"], abs=0.02)
    assert "YES" in note


def test_bet_no_when_ai_is_lower():
    bet, _ = trading.decide_bet(0.20, 0.40, 0.42, 0.0, equity=1000, cash=1000)
    assert bet["side"] == "NO" and bet["price"] == pytest.approx(0.60)


def test_no_bet_when_gap_is_small():
    bet, note = trading.decide_bet(0.55, 0.48, 0.50, 0.04, equity=1000, cash=1000)
    assert bet is None and "under" in note


def test_no_bet_when_out_of_cash():
    bet, _ = trading.decide_bet(0.90, 0.48, 0.50, 0.04, equity=1000, cash=0.50)
    assert bet is None


def test_payouts():
    yes = {"side": "YES", "shares": 10}
    no = {"side": "NO", "shares": 10}
    assert trading.payout(yes, 1) == 10 and trading.payout(yes, 0) == 0
    assert trading.payout(no, 0) == 10 and trading.payout(no, 1) == 0
    assert trading.payout(yes, "void") == 5


def test_replay_bankroll():
    q1, q2 = fake_question("a"), fake_question("b")
    q1["bet"] = {"side": "YES", "shares": 100, "cost": 42.0, "fee": 1.0}
    q2["bet"] = {"side": "NO", "shares": 50, "cost": 30.0, "fee": 0.5}
    days = [fake_day("2026-10-02", [q1, q2])]
    resolutions = {"a": {"outcome": 1, "resolved_at": "2026-10-05T00:00:00Z"}}
    result = trading.replay(days, resolutions, starting=1000)
    # a won: 1000 - 42 - 30 + 100 = 1028 cash; b still open (30 at cost)
    assert result["cash"] == 1028.0
    assert result["equity"] == 1058.0
    assert [q["market_id"] for q in result["open"]] == ["b"]
    assert result["settled"][0]["pnl"] == 58.0


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def test_brier_examples():
    assert scoring.brier(0.8, 1) == pytest.approx(0.04)
    assert scoring.brier(0.8, 0) == pytest.approx(0.64)


def test_summary_and_calibration():
    rows = [
        {"ai": 0.9, "crowd": 0.6, "outcome": 1},
        {"ai": 0.2, "crowd": 0.4, "outcome": 0},
        {"ai": 0.7, "crowd": 0.5, "outcome": 0},
    ]
    for r in rows:
        r["ai_brier"], r["crowd_brier"] = scoring.brier(r["ai"], r["outcome"]), scoring.brier(r["crowd"], r["outcome"])
    s = scoring.summary(rows)
    assert s["n"] == 3
    assert s["ai_brier"] == pytest.approx((0.01 + 0.04 + 0.49) / 3, abs=1e-4)
    assert s["crowd_brier"] == pytest.approx((0.16 + 0.16 + 0.25) / 3, abs=1e-4)
    assert s["ai_closer"] == 2 and s["crowd_closer"] == 1
    assert s["ci_low"] < s["diff"] < s["ci_high"]
    cal = scoring.calibration(rows, "ai")
    assert [c["bin"] for c in cal] == [2, 7, 9]
    assert scoring.summary([]) == {"n": 0}


def test_void_and_excluded_questions_are_not_scored():
    q1, q2, q3 = fake_question("a"), fake_question("b"), fake_question("c")
    for q in (q1, q2, q3):
        q["forecast"] = {"probability": 0.6, "reasoning": ""}
    q3["excluded"] = "closed early"
    resolutions = {m: {"outcome": o, "resolved_at": "2026-10-05T00:00:00Z"}
                   for m, o in (("a", 1), ("b", "void"), ("c", 0))}
    rows = scoring.scored_questions([fake_day("2026-10-02", [q1, q2, q3])], resolutions)
    assert [r["market_id"] for r in rows] == ["a"]


def test_check_resolutions_adds_results_without_touching_forecasts():
    q = fake_question("a")
    q["forecast"] = {"probability": 0.3, "reasoning": "R"}
    days = [fake_day("2026-10-02", [q])]
    before = json.dumps(days, sort_keys=True)
    resolutions = {}
    settled_market = {"closed": True, "outcomePrices": '["0", "1"]', "closedTime": "2026-10-04 18:46:00.2+00"}
    newly, failures = check_resolutions(days, resolutions, fetch=lambda _id: settled_market)
    assert newly == ["a"] and failures == 0
    assert resolutions["a"]["outcome"] == 0
    assert resolutions["a"]["resolved_at"] == "2026-10-04T18:46:00Z"
    assert json.dumps(days, sort_keys=True) == before


# ---------------------------------------------------------------------------
# The whole daily run, with everything faked
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def no_internet(monkeypatch):
    """Makes sure no test can reach the real internet by accident."""
    def blocked(*args, **kwargs):
        raise RuntimeError("Tests must not use the internet")
    monkeypatch.setattr("requests.get", blocked)
    monkeypatch.setattr("requests.post", blocked)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """Runs in an empty temporary folder with fake Polymarket and news."""
    monkeypatch.chdir(tmp_path)
    events = [fake_event("e1", ["politics"], [fake_market("1"), fake_market("2", bid=0.20, ask=0.22)]),
              fake_event("e2", ["economy"], [fake_market("3")])]
    monkeypatch.setattr(markets, "fetch_events", lambda: events)
    by_id = {m["id"]: m for e in events for m in e["markets"]}
    monkeypatch.setattr(markets, "fetch_market", lambda market_id: by_id[market_id])
    monkeypatch.setattr(news, "fetch_news", lambda q: [{"title": "Headline", "source": "AP"}])
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.setattr(main, "load_dotenv", lambda: None)
    return tmp_path


def run_main(monkeypatch, client, *args):
    monkeypatch.setattr(forecaster, "make_client", lambda key: client)
    monkeypatch.setattr(sys, "argv", ["main.py", *args])
    main.main()


ANSWER = {"forecasts": [
    {"id": "Q1", "probability_pct": 75, "reasoning": "Strong evidence."},
    {"id": "Q2", "probability_pct": 42, "reasoning": "Close call."},
    {"id": "Q3", "probability_pct": 10, "reasoning": "Unlikely."},
]}


def test_daily_run_saves_forecasts_and_bets(workspace, monkeypatch):
    run_main(monkeypatch, fake_client(answer=ANSWER))
    files = list((workspace / "data" / "forecasts").glob("*.json"))
    assert len(files) == 1
    day = json.loads(files[0].read_text())
    assert day["model"] == config.MODEL
    assert all(q["forecast"] for q in day["questions"])
    assert any(q["bet"] for q in day["questions"])          # 75% vs ~41% crowd -> a bet
    assert not list((workspace / "data" / "pending").glob("*.json"))


def test_second_run_same_day_does_not_forecast_again(workspace, monkeypatch):
    client = fake_client(answer=ANSWER)
    run_main(monkeypatch, client)
    run_main(monkeypatch, client)
    assert len(client.messages.batches.created) == 1
    assert len(list((workspace / "data" / "forecasts").glob("*.json"))) == 1


def test_force_adds_a_new_round_without_overwriting(workspace, monkeypatch):
    client = fake_client(answer=ANSWER)
    run_main(monkeypatch, client)
    run_main(monkeypatch, client, "--force")
    # All 3 questions were already used, so the forced round finds nothing new.
    assert len(client.messages.batches.created) == 1
    assert storage.new_run_id(datetime.now(timezone.utc).strftime("%Y-%m-%d")).endswith("-2")


def test_unfinished_batch_is_kept_pending_then_collected(workspace, monkeypatch):
    monkeypatch.setattr(config, "BATCH_WAIT_MINUTES", 0)
    client = fake_client(answer=ANSWER, status="in_progress")
    run_main(monkeypatch, client)
    assert len(list((workspace / "data" / "pending").glob("*.json"))) == 1
    assert not (workspace / "data" / "forecasts").exists()
    client.messages.batches.status = "ended"
    run_main(monkeypatch, client)
    assert len(list((workspace / "data" / "forecasts").glob("*.json"))) == 1
    assert not list((workspace / "data" / "pending").glob("*.json"))
    assert len(client.messages.batches.created) == 1        # not re-sent


def test_refused_batch_is_recorded_not_retried(workspace, monkeypatch):
    client = fake_client(stop_reason="refusal")
    run_main(monkeypatch, client)
    day = json.loads(next((workspace / "data" / "forecasts").glob("*.json")).read_text())
    assert "declined" in day["error"]
    assert all(q["forecast"] is None for q in day["questions"])


def test_forecast_files_are_never_overwritten(workspace):
    storage.save_forecast({"run_id": "2026-10-02", "questions": []})
    with pytest.raises(FileExistsError):
        storage.save_forecast({"run_id": "2026-10-02", "questions": []})


def test_dry_run_saves_nothing(workspace, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["main.py", "--dry-run"])
    main.main()
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "Crowd prices (hidden from Claude)" in out
    assert not (workspace / "data").exists()


# ---------------------------------------------------------------------------
# Website data and Discord
# ---------------------------------------------------------------------------

def test_site_data_is_compact_and_complete(tmp_path):
    q1, q2 = fake_question("a"), fake_question("b")
    q1["forecast"] = {"probability": 0.8, "reasoning": "R"}
    q2["forecast"] = {"probability": 0.3, "reasoning": "R"}
    q1["bet"] = {"side": "YES", "price": 0.42, "shares": 50, "stake": 21, "fee": 0.5, "cost": 21.5, "gap_pts": 38}
    days = [fake_day("2026-10-02", [q1, q2])]
    resolutions = {"a": {"outcome": 1, "resolved_at": "2026-10-05T00:00:00Z"}}
    data = build_site.build_data(days, resolutions)
    assert data["stats"]["n"] == 1
    assert [r["id"] for r in data["open"]] == ["b"]
    assert data["settled"][0]["pnl"] == 28.5
    assert data["portfolio"]["equity"] == 1028.5
    path = tmp_path / "data.js"
    build_site.write_data(data, path=str(path))
    text = path.read_text()
    assert text.startswith("window.FORECAST_DATA = {") and ", " not in text[:200]
    # Rebuilding with only a new time doesn't rewrite the file.
    assert build_site.write_data({**data, "generated_at": "later"}, path=str(path)) is False
    assert build_site.write_data({**data, "total_cost": 1.0}, path=str(path)) is True


def test_discord_message_has_disclaimer_and_splits(workspace):
    message = discord_notify.build_message([], [], {}, ["Something failed"])
    assert message.endswith(f"_{config.DISCLAIMER}_")
    long = "\n".join(["x" * 150] * 40)
    assert all(len(c) <= discord_notify.DISCORD_LIMIT for c in discord_notify.split_message(long))


# ---------------------------------------------------------------------------
# Live prices and analysis
# ---------------------------------------------------------------------------

def test_record_price_keeps_one_point_per_day():
    prices = {}
    record_price(prices, "a", fake_market(bid=0.40, ask=0.42), "2026-10-03")
    record_price(prices, "a", fake_market(bid=0.50, ask=0.52), "2026-10-03")   # same day: replaced
    record_price(prices, "a", fake_market(bid=0.60, ask=0.62), "2026-10-04")
    assert prices == {"a": [["2026-10-03", 0.51], ["2026-10-04", 0.61]]}


def test_results_check_records_prices_only_for_open_markets():
    q1, q2 = fake_question("a"), fake_question("b")
    for q in (q1, q2):
        q["forecast"] = {"probability": 0.6, "reasoning": "R"}
    live = {"a": fake_market("a", bid=0.45, ask=0.47),
            "b": {"closed": True, "outcomePrices": '["1", "0"]', "closedTime": "2026-10-04 00:00:00+00"}}
    prices = {}
    check_resolutions([fake_day("2026-10-02", [q1, q2])], {}, prices, fetch=live.get, today="2026-10-03")
    assert prices == {"a": [["2026-10-03", 0.46]]}


def test_crowd_movement_toward_the_ai():
    questions = [
        {"ai": 0.70, "crowd": 0.50, "latest": 0.60},   # +10 toward
        {"ai": 0.20, "crowd": 0.50, "latest": 0.55},   # -5 away
        {"ai": 0.51, "crowd": 0.50, "latest": 0.90},   # AI basically agreed: skipped
        {"ai": 0.90, "crowd": 0.50, "latest": None},   # no newer price: skipped
    ]
    assert scoring.movement(questions) == {"n": 2, "toward": 1, "away": 1, "avg_pts": 2.5}
    assert scoring.movement([]) == {"n": 0}


def test_bet_breakdown_groups():
    bets = [
        {"gap_pts": 12, "side": "YES", "topic": "Tech", "cost": 50, "pnl": 30},
        {"gap_pts": 25, "side": "NO", "topic": "Tech", "cost": 50, "pnl": -50},
        {"gap_pts": 40, "side": "NO", "topic": "Politics", "cost": 40, "pnl": 10},
    ]
    result = scoring.bet_breakdown(bets)
    assert [g["label"] for g in result["by_gap"]] == ["10-20 points", "20-30 points", "30+ points"]
    no = next(g for g in result["by_side"] if g["label"] == "Bought NO")
    assert no == {"label": "Bought NO", "n": 2, "wins": 1, "pnl": -40, "roi": -44.4}
    assert result["by_topic"][0]["label"] == "Tech"


def test_site_shows_live_value_blend_and_sparkline():
    q1, q2 = fake_question("a", crowd=0.40), fake_question("b", crowd=0.50)
    q1["forecast"] = {"probability": 0.70, "reasoning": "R"}
    q2["forecast"] = {"probability": 0.90, "reasoning": "R"}
    q1["bet"] = {"side": "YES", "price": 0.42, "shares": 100, "stake": 42, "fee": 1, "cost": 43, "gap_pts": 28}
    days = [fake_day("2026-10-02", [q1, q2])]
    resolutions = {"b": {"outcome": 1, "resolved_at": "2026-10-05T00:00:00Z"}}
    prices = {"a": [["2026-10-03", 0.50], ["2026-10-04", 0.55]]}
    data = build_site.build_data(days, resolutions, prices=prices)
    open_row = data["open"][0]
    assert open_row["latest"] == 0.55
    assert open_row["spark"] == [["2026-10-02", 0.40], ["2026-10-03", 0.50], ["2026-10-04", 0.55]]
    assert open_row["bet"]["value"] == 55.0              # 100 YES shares at 55 cents
    assert data["portfolio"]["unrealized"] == 12.0
    assert data["stats"]["blend_brier"] == pytest.approx(0.09, abs=1e-4)   # (0.7 - 1)^2
    assert data["movement"]["toward"] == 1
    assert [r["id"] for r in data["best"]] == ["b"]      # AI 90% beat crowd 50% on a YES
    assert data["latest_run"] == "2026-10-02"
