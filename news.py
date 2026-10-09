"""
news.py - Free news research for each question, from Google News.

Google News has a free RSS feed (a simple machine-readable list of
articles) for any search. No key, no cost. We take the top few headlines
for each question.

One rule matters a lot for the experiment: Claude must not see the market's
price, or it could just copy the crowd. News articles often quote what
markets think ("traders see a 70% chance", "hike priced in", "Polymarket
bettors..."), so any headline that sounds like a market's odds is thrown out.
"""

import html
import re
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import requests

import config
import groups

RSS_URL = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
HEADERS = {"User-Agent": "ai-forecaster-research/1.0"}

# Headlines matching any of these could leak what a market thinks, so they're
# dropped (we check the news source's name too, e.g. "Kalshi News").
# Widened on 2026-10-09 (Phase 1.1): headlines like "Fed officials wash away
# market bets" and "Options Traders Give Nvidia a 50% Chance" used to get
# through. Each pattern is tested against real headlines in the tests, both
# ones that must be dropped and normal news that must be kept.
LEAKY_WORDS = re.compile(
    r"polymarket|kalshi|manifold|predictit|prediction market|betting|bettors|\bbets?\b|"
    r"wager|sportsbook|\bodds\b|oddsmaker|bookmaker|bookie|punter|betfair|smarkets|fedwatch|"
    r"\bpric(ed|ing) (in|out)\b|market pricing|"
    r"\b(traders|investors|markets?|options traders)( now)? (see|expect|bet|price|slash|pare|put|give)\b|"
    r"\bimplied\b|probabilit|\d+(\.\d+)?\s?% (chance|probability|likelihood)",
    re.IGNORECASE,
)

# Words that don't help a news search.
STOPWORDS = {
    "will", "the", "a", "an", "be", "by", "of", "in", "on", "at", "to", "for",
    "after", "before", "is", "are", "does", "do", "there", "any", "than", "or",
    "and", "with", "get", "have", "has", "end", "next", "between", "less", "more",
    "least", "most", "over", "under", "above", "below", "reach", "hit", "hits",
    "million", "billion", "day", "week", "month", "year", "its", "this", "that",
    "who", "what", "which", "when", "how", "no", "not", "yes", "new", "from",
    "make", "makes", "officially", "itself",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "jan", "feb", "mar", "apr",
    "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
}

MAX_PER_SOURCE = 2   # so one site can't fill the whole list
MIN_GOOD_RESULTS = 3  # try the next search if the first finds fewer than this


def _keywords(text, limit=7):
    """The useful words in a bit of text: no dates, numbers or filler."""
    words = []
    for word in re.findall(r"[A-Za-zÀ-ÿ][\w'&.-]*", text):
        word = re.sub(r"'s$", "", word).strip(".-")
        if len(word) < 2 or word.lower() in STOPWORDS or any(c.isdigit() for c in word):
            continue
        if word.lower() not in (w.lower() for w in words):
            words.append(word)
    return words[:limit]


def build_queries(question):
    """
    The news searches to try for one question, best first. For example
    "Will Apple be the second-largest company in the world by market cap on
    October 31, 2026?" -> "Apple second-largest company world market cap".
    Dates, numbers, "by...", "__" and filler words are removed, because they
    made Google return nothing. The event's title plus the option (like a
    candidate's name) is the backup search.
    """
    queries = [" ".join(_keywords(question["question"]))]
    if question.get("event_title"):
        backup = " ".join(_keywords(f"{question['event_title']} {question.get('option') or ''}"))
        if backup and backup not in queries:
            queries.append(backup)
    return [q for q in queries if q]


def build_query(question):
    """The main news search for a question (see build_queries)."""
    queries = build_queries(question)
    return queries[0] if queries else question["question"]


def _clean(text):
    """Removes HTML tags and extra spaces from a bit of text."""
    text = re.sub(r"<[^>]+>", " ", html.unescape(text or ""))
    return re.sub(r"\s+", " ", text).strip()


def is_leaky(*texts):
    """True if any of the texts sounds like it reports a market's odds."""
    return any(LEAKY_WORDS.search(t or "") for t in texts)


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
        if not title or is_leaky(title, summary, source):
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


def is_relevant(headline, question):
    """
    Keeps only headlines about the question's subject. If the question names
    something (Apple, ECB, Rhine...), the headline must name it too, so a
    search for "Apple market cap" can't fill up with Apple TV trailers' cousins
    about other companies. Otherwise any main keyword will do.
    """
    text = f"{headline['title']} {headline.get('summary') or ''}".lower()
    names = groups.key_names(question)
    if names:
        return any(re.search(r"\b" + re.escape(n[:6]), text) for n in names)
    words = [w.lower() for w in _keywords(question["question"]) if len(w) >= 4]
    return not words or any(w in text for w in words)


def _search(query):
    """One Google News search, retried once if Google has a hiccup."""
    url = RSS_URL.format(query=quote_plus(f"{query} when:{config.NEWS_LOOKBACK}"))
    for attempt in range(2):
        try:
            response = requests.get(url, headers=HEADERS, timeout=30)
            if response.status_code >= 500 and attempt == 0:
                time.sleep(2)
                continue
            response.raise_for_status()
            return parse_rss(response.text, 40)
        except requests.ConnectionError:
            if attempt == 1:
                raise
            time.sleep(2)
    raise RuntimeError("Google News kept failing")


def fetch_news(question, limit=None):
    """
    Searches Google News for one question. Returns {"headlines": [...],
    "query": "the search used"}. Raises an exception if every search failed.
    """
    limit = limit or config.HEADLINES_PER_QUESTION
    found, used, per_source = [], [], {}
    for query in build_queries(question):
        used.append(query)
        for h in _search(query):
            if len(found) == limit:
                break
            if any(h["title"] == f["title"] for f in found) or not is_relevant(h, question):
                continue
            if per_source.get(h["source"], 0) >= MAX_PER_SOURCE:
                continue
            per_source[h["source"]] = per_source.get(h["source"], 0) + 1
            found.append(h)
        if len(found) >= MIN_GOOD_RESULTS:
            break
    return {"headlines": found, "query": " | ".join(used)}
