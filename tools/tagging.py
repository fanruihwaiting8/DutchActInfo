"""Cross-source tagging: which events belong to a Dutch seasonal festivity.

Carnaval, Sinterklaas, Christmas markets and the winter light festivals are
spread over every source we scrape (a Sinterklaas show sits in the theatre
agenda, a Christmas market in the festival agenda, a lantern walk in the
museum agenda). Instead of inventing a category for them we keep the source
category and add a boolean flag, so "Seasonal" can be offered as its own
filter without losing what kind of event it is.

Titles are the reliable signal. Descriptions mention the season far too
casually ("open during the Christmas holidays"), so only unmistakable words
count there.
"""

from __future__ import annotations

import re

# Matched against the title.
TITLE_WORDS = (
    r"carnaval",
    r"carnival",
    r"sinterklaas",
    r"sint[- ]nicolaas",
    r"piet(?:en)?\b",
    r"intocht",
    r"kerst",
    r"christmas",
    r"x-?mas",
    r"advent",
    r"winterfair",
    r"winter ?markt",
    r"wintermarkt",
    r"winter wonder",
    r"lichtjes",
    r"lichtfestival",
    r"light festival",
    r"halloween",
    r"sint[- ]maarten",
    r"st\.? maarten",
    r"lampion",
    r"oud(?:e)?jaar",
    r"oud ?(?:&|en) ?nieuw",
    r"nieuwjaar",
    r"new year",
    r"driekoningen",
    r"pasen",
    r"easter",
    r"koningsdag",
    r"king'?s day",
)
# Matched against the description as well: these are never used in passing.
STRONG_WORDS = (
    r"carnaval",
    r"carnival",
    r"sinterklaas",
    r"kerstmarkt",
    r"christmas market",
    r"halloween",
    r"winterfair",
)

TITLE_RE = re.compile(r"(?:" + r"|".join(TITLE_WORDS) + r")", re.IGNORECASE)
STRONG_RE = re.compile(r"(?:" + r"|".join(STRONG_WORDS) + r")", re.IGNORECASE)


def is_seasonal(title: str, description: str = "") -> bool:
    """True when the event is tied to a seasonal festivity."""
    if title and TITLE_RE.search(title):
        return True
    return bool(description and STRONG_RE.search(description))