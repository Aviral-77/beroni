"""
Central configuration for the FMCG M&A Intelligence pipeline.

Everything that a human might reasonably want to tune — news sources,
keyword vocabularies, source-credibility tiers and pipeline thresholds —
lives here so the rest of the codebase stays declarative and transparent.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 1. SOURCES (ingestion)
# ---------------------------------------------------------------------------
# We rely exclusively on *public* RSS/Atom feeds — no paid APIs, no scraping
# behind paywalls. Google News RSS lets us run targeted queries while still
# attributing each item to its original publisher (via the <source> tag),
# which we then credibility-score. Direct trade-press feeds add depth.
#
# Each source: name, url, type ("google_news" | "rss"), and a hint tier used
# only when the per-article publisher cannot be resolved.

GOOGLE_NEWS_QUERIES = [
    'FMCG acquisition',
    'FMCG merger',
    'consumer goods acquisition',
    'CPG acquisition',
    'food company acquisition',
    'beverage company acquisition',
    'personal care brand acquisition',
    'consumer brand investment funding',
    'packaged food merger OR acquisition',
    'FMCG private equity stake',
]

# Direct publisher feeds (trade & business press). These are stable, public RSS.
DIRECT_FEEDS = [
    {"name": "Food Dive",        "url": "https://www.fooddive.com/feeds/news/",        "type": "rss"},
    {"name": "Grocery Dive",     "url": "https://www.grocerydive.com/feeds/news/",     "type": "rss"},
    {"name": "Retail Dive",      "url": "https://www.retaildive.com/feeds/news/",      "type": "rss"},
    {"name": "Just Food",        "url": "https://www.just-food.com/feed/",             "type": "rss"},
    {"name": "Just Drinks",      "url": "https://www.just-drinks.com/feed/",           "type": "rss"},
    {"name": "FoodBev Media",    "url": "https://www.foodbev.com/feed/",               "type": "rss"},
    {"name": "Beverage Daily",   "url": "https://www.beveragedaily.com/info/rss",      "type": "rss"},
]


def google_news_rss(query: str, lang: str = "en-US", country: str = "US") -> str:
    """Build a Google News RSS search URL for a query."""
    from urllib.parse import quote_plus
    ceid = f"{country}:{lang.split('-')[0]}"
    return (
        f"https://news.google.com/rss/search?q={quote_plus(query)}"
        f"&hl={lang}&gl={country}&ceid={ceid}"
    )


def all_sources() -> list[dict]:
    """Return the full list of feed source definitions."""
    sources: list[dict] = [
        {"name": f"Google News: {q}", "url": google_news_rss(q), "type": "google_news"}
        for q in GOOGLE_NEWS_QUERIES
    ]
    sources.extend(DIRECT_FEEDS)
    return sources


# ---------------------------------------------------------------------------
# 2. RELEVANCE VOCABULARY (scoring)
# ---------------------------------------------------------------------------
# Relevance is gated on TWO independent signals: the item must look like a
# DEAL *and* be about an FMCG/consumer-goods subject. Weights let strong,
# unambiguous terms ("acquisition") count for more than weak ones ("talks").

# Deal / transaction vocabulary  -> weight
DEAL_KEYWORDS: dict[str, int] = {
    # strong, unambiguous M&A signals
    "acquisition": 3, "acquire": 3, "acquires": 3, "acquired": 3, "acquiring": 3,
    "merger": 3, "merges": 3, "merge with": 3, "to merge": 3,
    "takeover": 3, "buyout": 3, "buy-out": 3, "leveraged buyout": 3, "lbo": 3,
    "to buy": 3, "agrees to buy": 3, "agreed to buy": 3, "deal to acquire": 3,
    "majority stake": 3, "controlling stake": 3, "divest": 3, "divests": 3,
    "divestiture": 3, "divestment": 3, "sells unit": 3, "sells business": 3,
    "sells brand": 3, "snaps up": 3, "scoops up": 3,
    # medium investment / capital-markets signals
    # (note: bare "raises/raised" deliberately excluded — it false-fires on
    #  "raised guidance"; funding is caught via "funding round"/"series x"/"$")
    "investment": 2, "invests": 2, "invest in": 2, "funding round": 2,
    "series a": 2, "series b": 2, "series c": 2,
    "series d": 2, "venture round": 2, "private equity": 2, "minority stake": 2,
    "stake": 2, "joint venture": 2, "ipo": 2, "public offering": 2,
    "backed by": 2, "backs": 2, "valuation": 2, "spin off": 2, "spin-off": 2,
    "spinoff": 2, "carve-out": 2, "carve out": 2,
    # weaker / exploratory signals (often pre-deal chatter)
    "deal": 1, "in talks": 1, "talks to": 1, "explores sale": 1,
    "exploring sale": 1, "considering sale": 1, "bid for": 1, "offer for": 1,
    "financing": 1, "capital raise": 1, "fundraise": 1,
}

# FMCG / consumer-goods subject vocabulary (categories) -> weight
FMCG_CATEGORY_KEYWORDS: dict[str, int] = {
    "fmcg": 3, "cpg": 3, "consumer packaged goods": 3, "consumer goods": 3,
    "packaged food": 2, "packaged goods": 2, "grocery": 2, "supermarket": 1,
    "food": 1, "beverage": 2, "drinks": 1, "soft drink": 2, "bottled water": 2,
    "snack": 2, "confectionery": 2, "chocolate": 2, "candy": 2, "biscuit": 2,
    "dairy": 2, "cheese": 1, "yogurt": 2, "yoghurt": 2, "cereal": 2,
    "frozen food": 2, "ready meals": 2, "baby food": 2, "infant formula": 2,
    "pet food": 2, "nutrition": 1, "supplement": 2, "coffee": 1, "tea": 1,
    "brewer": 2, "brewery": 2, "beer": 1, "spirits": 2, "distillery": 2,
    "wine": 1, "personal care": 3, "beauty": 2, "cosmetics": 3, "skincare": 2,
    "haircare": 2, "hair care": 2, "oral care": 2, "household": 2,
    "home care": 2, "cleaning products": 2, "detergent": 2, "hygiene": 2,
    "tobacco": 2, "vaping": 1, "consumer health": 2, "wellness brand": 1,
}

# Well-known FMCG companies / brands -> weight (a named major is a strong cue)
FMCG_COMPANY_KEYWORDS: dict[str, int] = {
    k: 3 for k in [
        "nestle", "nestlé", "unilever", "procter & gamble", "procter and gamble",
        "p&g", "pepsico", "pepsi", "coca-cola", "coca cola", "mondelez",
        "danone", "kraft heinz", "general mills", "kellanova", "kellogg",
        "mars inc", "mars wrigley", "colgate", "colgate-palmolive", "reckitt",
        "henkel", "l'oreal", "l'oréal", "loreal", "estee lauder", "estée lauder",
        "heineken", "ab inbev", "anheuser-busch", "diageo", "pernod ricard",
        "carlsberg", "beiersdorf", "church & dwight", "clorox", "conagra",
        "hershey", "tyson foods", "jbs", "associated british foods", "britvic",
        "suntory", "keurig dr pepper", "molson coors", "constellation brands",
        "campbell", "campbell's", "mccormick", "post holdings", "hormel",
        "lactalis", "arla", "saputo", "haleon", "kenvue", "nestle waters",
        "bimbo", "grupo bimbo", "ferrero", "barilla", "kimberly-clark",
        "edgewell", "coty", "shiseido", "unicharm", "kao",
    ]
}


# ---------------------------------------------------------------------------
# 3. CREDIBILITY TIERS (scoring)
# ---------------------------------------------------------------------------
# Transparent, source-domain based credibility. We do NOT judge truthfulness
# of any individual claim — only the *track record / editorial standing* of the
# outlet, plus a corroboration bonus when multiple independent outlets report
# the same story (handled in score.py). Press-release wires are factual for
# announcements but are primary PR rather than independent journalism, so we
# flag them and cap their standalone credibility.

CREDIBILITY_TIERS: dict[str, dict] = {
    "tier1": {
        "score": 95,
        "label": "Tier 1 — global wire / financial press",
        "domains": [
            "reuters.com", "bloomberg.com", "ft.com", "wsj.com", "apnews.com",
            "cnbc.com", "forbes.com", "nytimes.com", "economist.com",
            "theguardian.com", "bbc.com", "bbc.co.uk", "marketwatch.com",
            "businessinsider.com", "fortune.com", "axios.com",
        ],
    },
    "tier2": {
        "score": 85,
        "label": "Tier 2 — established trade / industry press",
        "domains": [
            "fooddive.com", "grocerydive.com", "retaildive.com", "just-food.com",
            "just-drinks.com", "foodbev.com", "beveragedaily.com",
            "foodnavigator.com", "confectionerynews.com", "dairyreporter.com",
            "cosmeticsdesign.com", "cosmeticsbusiness.com", "thegrocer.co.uk",
            "supermarketnews.com", "consumergoods.com", "pymnts.com",
            "grocerygazette.co.uk", "foodmanufacture.co.uk", "citywire.com",
        ],
    },
    "tier3": {
        "score": 70,
        "label": "Tier 3 — general / regional / market news",
        "domains": [
            "finance.yahoo.com", "yahoo.com", "seekingalpha.com", "benzinga.com",
            "investing.com", "thestreet.com", "cityam.com", "msn.com",
            "nasdaq.com", "fool.com", "barrons.com",
        ],
    },
    "press_release": {
        "score": 55,
        "label": "Press-release wire (primary PR — flagged)",
        "domains": [
            "prnewswire.com", "businesswire.com", "globenewswire.com",
            "einpresswire.com", "accesswire.com", "prweb.com",
            "newswire.com", "presswire.com",
        ],
    },
}

DEFAULT_CREDIBILITY = {"score": 50, "label": "Unknown / unverified source"}


# ---------------------------------------------------------------------------
# 4. PIPELINE THRESHOLDS
# ---------------------------------------------------------------------------
THRESHOLDS = {
    # ingestion
    "lookback_days": 14,        # only keep items published within N days
    "max_items_per_feed": 40,   # cap per feed to keep things tidy & polite
    # de-duplication (near-dup similarity = blend of shared-entity overlap and
    # shared-content overlap; see clean.similarity)
    "near_dup_similarity": 0.50,  # merge stories at/above this blended overlap
    "entity_weight": 0.5,         # weight for shared named-entity/number overlap
    "content_weight": 0.5,        # weight for shared significant-content overlap
    # relevance
    "min_relevance": 35,        # items below this are filtered out of the draft
    # newsletter
    "lead_deals": 6,            # number of headline "lead" stories
    "brief_mentions": 8,        # number of shorter "also in the news" items
}

# Composite ranking weights (how we order stories in the newsletter)
RANK_WEIGHTS = {
    "relevance": 0.45,
    "credibility": 0.30,
    "recency": 0.15,
    "corroboration": 0.10,
}
