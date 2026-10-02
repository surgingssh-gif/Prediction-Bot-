"""
news.py - Free news research for each question, from Google News.

Google News has a free RSS feed (a simple machine-readable list of
articles) for any search. No key, no cost. We take the top few headlines
for each question.

One rule matters a lot for the experiment: Claude must not see the market's
price, or it could just copy the crowd. News articles sometimes quote
prediction-market odds ("Polymarket bettors give X a 70% chance"), so any
headline that mentions a prediction market is thrown out.
"""

import html
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import requests

import config

RSS_URL = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
HEADERS = {"User-Agent": "ai-forecaster-research/1.0"}

# Headlines mentioning any of these could leak the crowd's price, so they're
# dropped (we check the news source's name too, e.g. "Kalshi News"). "Odds"
# headlines usually quote a market's price, so they go as well.
LEAKY_WORDS = re.compile(
    r"polymarket|kalshi|manifold|predictit|prediction market|betting|bettors|"
    r"sportsbook|\bodds\b",
    re.IGNORECASE,
)

# Little words that don't help a news search.
STOPWORDS = {
    "will", "the", "a", "an", "be", "by", "of", "in", "on", "at", "to", "for",
    "after", "before", "is", "are", "does", "do", "there", "any", "than", "or",
    "and", "with", "get", "have", "has", "end", "next",
}


def build_query(question):
    """
    Turns a question into a short news search, e.g.
    "Will the Fed cut rates after the October 2026 meeting?"
      -> "Fed cut rates October 2026 meeting"
    For multi-option events we search the event plus the option
    ("Brazil Presidential Election Lula"), which finds better news.
    """
    if question.get("option") and question.get("event_title"):
        text = f"{question['event_title']} {question['option']}"
    else:
        text = question["question"]
    words = re.findall(r"[\w$%.'-]+", text)
    words = [w for w in words if w.lower() not in STOPWORDS]
    return " ".join(words[:10])


def _clean(text):
    """Removes HTML tags and extra spaces from a bit of text."""
    text = re.sub(r"<[^>]+>", " ", html.unescape(text or ""))
    return re.sub(r"\s+", " ", text).strip()


def parse_rss(xml_text, limit):
    """Reads Google News RSS text into a list of headline dicts."""
    root = ET.fromstring(xml_text)
    headlines = []
    for item in root.iter("item"):
        title = _clean(item.findtext("title"))
        source = _clean(item.findtext("source"))
        # Google puts " - Source Name" at the end of every title; drop it.
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3]
        summary = _clean(item.findtext("description"))
        # The "summary" is often just the title again; only keep it if it adds something.
        if summary.startswith(title) or title.startswith(summary[:60]):
            summary = ""
        if not title or any(LEAKY_WORDS.search(text) for text in (title, summary, source)):
            continue
        published = None
        try:
            published = parsedate_to_datetime(item.findtext("pubDate")).strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            pass
        headlines.append({
            "title": title,
            "source": source,
            "published": published,
            "summary": summary[:300],
            "link": item.findtext("link"),
        })
        if len(headlines) == limit:
            break
    return headlines


def fetch_news(question, limit=None):
    """Searches Google News for one question. Raises an exception on failure."""
    limit = limit or config.HEADLINES_PER_QUESTION
    query = f"{build_query(question)} when:{config.NEWS_LOOKBACK}"
    response = requests.get(RSS_URL.format(query=quote_plus(query)), headers=HEADERS, timeout=30)
    response.raise_for_status()
    return parse_rss(response.text, limit)
