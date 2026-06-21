from urllib.parse import quote_plus

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

DIRECT_FEEDS = [
    {"name": "Food Dive",      "url": "https://www.fooddive.com/feeds/news/",    "type": "rss"},
    {"name": "Grocery Dive",   "url": "https://www.grocerydive.com/feeds/news/", "type": "rss"},
    {"name": "Retail Dive",    "url": "https://www.retaildive.com/feeds/news/",  "type": "rss"},
    {"name": "Just Food",      "url": "https://www.just-food.com/feed/",         "type": "rss"},
    {"name": "Just Drinks",    "url": "https://www.just-drinks.com/feed/",       "type": "rss"},
    {"name": "FoodBev Media",  "url": "https://www.foodbev.com/feed/",           "type": "rss"},
    {"name": "Beverage Daily", "url": "https://www.beveragedaily.com/info/rss",  "type": "rss"},
]


def google_news_rss(query, lang="en-US", country="US"):
    ceid = f"{country}:{lang.split('-')[0]}"
    return (
        f"https://news.google.com/rss/search?q={quote_plus(query)}"
        f"&hl={lang}&gl={country}&ceid={ceid}"
    )


def all_sources():
    sources = [
        {"name": f"Google News: {q}", "url": google_news_rss(q), "type": "google_news"}
        for q in GOOGLE_NEWS_QUERIES
    ]
    sources.extend(DIRECT_FEEDS)
    return sources


# Deal / transaction vocabulary -> weight
# Note: bare "raises/raised" is excluded because it fires on "raised guidance"
DEAL_KEYWORDS = {
    "acquisition": 3, "acquire": 3, "acquires": 3, "acquired": 3, "acquiring": 3,
    "merger": 3, "merges": 3, "merge with": 3, "to merge": 3,
    "takeover": 3, "buyout": 3, "buy-out": 3, "leveraged buyout": 3, "lbo": 3,
    "to buy": 3, "agrees to buy": 3, "agreed to buy": 3, "deal to acquire": 3,
    "majority stake": 3, "controlling stake": 3, "divest": 3, "divests": 3,
    "divestiture": 3, "divestment": 3, "sells unit": 3, "sells business": 3,
    "sells brand": 3, "snaps up": 3, "scoops up": 3,
    "investment": 2, "invests": 2, "invest in": 2, "funding round": 2,
    "series a": 2, "series b": 2, "series c": 2,
    "series d": 2, "venture round": 2, "private equity": 2, "minority stake": 2,
    "stake": 2, "joint venture": 2, "ipo": 2, "public offering": 2,
    "backed by": 2, "backs": 2, "valuation": 2, "spin off": 2, "spin-off": 2,
    "spinoff": 2, "carve-out": 2, "carve out": 2,
    "deal": 1, "in talks": 1, "talks to": 1, "explores sale": 1,
    "exploring sale": 1, "considering sale": 1, "bid for": 1, "offer for": 1,
    "financing": 1, "capital raise": 1, "fundraise": 1,
}

FMCG_CATEGORY_KEYWORDS = {
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

FMCG_COMPANY_KEYWORDS = {
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

CREDIBILITY_TIERS = {
    "tier1": {
        "score": 95,
        "label": "Tier 1 - global wire / financial press",
        "domains": [
            "reuters.com", "bloomberg.com", "ft.com", "wsj.com", "apnews.com",
            "cnbc.com", "forbes.com", "nytimes.com", "economist.com",
            "theguardian.com", "bbc.com", "bbc.co.uk", "marketwatch.com",
            "businessinsider.com", "fortune.com", "axios.com",
        ],
    },
    "tier2": {
        "score": 85,
        "label": "Tier 2 - established trade / industry press",
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
        "label": "Tier 3 - general / regional / market news",
        "domains": [
            "finance.yahoo.com", "yahoo.com", "seekingalpha.com", "benzinga.com",
            "investing.com", "thestreet.com", "cityam.com", "msn.com",
            "nasdaq.com", "fool.com", "barrons.com",
        ],
    },
    "press_release": {
        "score": 55,
        "label": "Press-release wire (primary PR - flagged)",
        "domains": [
            "prnewswire.com", "businesswire.com", "globenewswire.com",
            "einpresswire.com", "accesswire.com", "prweb.com",
            "newswire.com", "presswire.com",
        ],
    },
}

DEFAULT_CREDIBILITY = {"score": 50, "label": "Unknown / unverified source"}

THRESHOLDS = {
    "lookback_days": 14,
    "max_items_per_feed": 40,
    "near_dup_similarity": 0.50,
    "entity_weight": 0.5,
    "content_weight": 0.5,
    "min_relevance": 35,
    "lead_deals": 6,
    "brief_mentions": 8,
}

RANK_WEIGHTS = {
    "relevance": 0.45,
    "credibility": 0.30,
    "recency": 0.15,
    "corroboration": 0.10,
}
