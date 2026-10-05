"""
groups.py - Spots questions about the same real-world story.

Polymarket often splits one story into many separate "events". The Brazil
election, for example, had separate events for the winner, the first-round
winner, second place and the margin of victory. If all of those go the same
way, every bet on them wins or loses together, so betting on several of them
is really one big bet.

Two questions count as RELATED if they share a distinctive name: a country,
person, company or thing (Brazil, Lula, Gemini, OpenAI, Rhine...). Common
words like "election", "October" or "AI" don't count.
"""

import re
import unicodedata

# Capitalized words that are too common to link two questions together.
GENERIC = {
    # question words and filler
    "will", "the", "which", "who", "what", "when", "how", "does", "next", "any",
    "end", "new", "top", "best", "more", "less", "than", "between",
    # dates
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "monday", "tuesday",
    "wednesday", "thursday", "friday", "saturday", "sunday", "day", "week",
    "month", "year", "monthly", "weekly", "daily", "jan", "feb", "mar", "apr",
    "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
    # answer options
    "yes", "not", "change", "other", "pro", "east", "west", "north", "south",
    # very broad places and groups
    "us", "usa", "uk", "eu", "world", "global", "international", "national",
    # common market words
    "ai", "election", "elections", "presidential", "president", "first", "round",
    "second", "place", "winner", "margin", "victory", "decision", "interest",
    "rate", "rates", "company", "companies", "model", "models", "total",
    "domestic", "gross", "prime", "minister", "bank", "image", "edit", "chinese",
    "largest", "biggest", "market", "cap", "price", "high", "low", "release",
    "released", "return", "normal", "levels", "views", "video", "listeners",
    "announce", "official", "officially",
}


def _plain(word):
    """Lowercase, without accents (so "Flávio" matches "Flavio")."""
    word = unicodedata.normalize("NFKD", word)
    return "".join(c for c in word if not unicodedata.combining(c)).lower()


def key_names(question):
    """
    The distinctive names in a question, e.g. {"brazil", "lula"}.
    Uses the event title, the option (like a candidate's name) and the question.
    """
    text = " ".join(question.get(k) or "" for k in ("event_title", "option", "question"))
    names = set()
    for word in re.findall(r"[^\W\d_]+", text):
        if not word[0].isupper() or len(word) < 3:
            continue  # only capitalized words, like names
        plain = _plain(word)
        if plain not in GENERIC:
            names.add(plain)
    return names


def _same_name(a, b):
    """True for the same name, or one form of it ("brazil" / "brazilian")."""
    if a == b:
        return True
    short, long = sorted((a, b), key=len)
    return len(short) >= 4 and long.startswith(short)


def related(q1, q2):
    """True if two questions share a distinctive name."""
    names1, names2 = key_names(q1), key_names(q2)
    return any(_same_name(a, b) for a in names1 for b in names2)
