import re
from datetime import datetime, timezone

from . import config


def _weighted_hits(text, vocab):
    total, matched = 0, []
    for term, weight in vocab.items():
        if term in text:
            total += weight
            matched.append(term)
    return total, matched


def score_relevance(article):
    title = (article.get("title") or "").lower()
    summary = (article.get("summary") or "").lower()

    deal_t, deal_tm = _weighted_hits(title, config.DEAL_KEYWORDS)
    deal_s, deal_sm = _weighted_hits(summary, config.DEAL_KEYWORDS)
    fmcg_vocab = {**config.FMCG_CATEGORY_KEYWORDS, **config.FMCG_COMPANY_KEYWORDS}
    fmcg_t, fmcg_tm = _weighted_hits(title, fmcg_vocab)
    fmcg_s, fmcg_sm = _weighted_hits(summary, fmcg_vocab)

    deal_signal = deal_t * 2 + deal_s   # title counts double
    fmcg_signal = fmcg_t * 2 + fmcg_s

    is_relevant = deal_signal > 0 and fmcg_signal > 0

    norm_deal = min(deal_signal, 10) / 10.0
    norm_fmcg = min(fmcg_signal, 10) / 10.0
    score = round(100 * (0.55 * norm_deal + 0.45 * norm_fmcg))

    if not is_relevant:
        score = min(score, 20)

    return {
        "relevance": score,
        "is_relevant": is_relevant,
        "deal_signal": deal_signal,
        "fmcg_signal": fmcg_signal,
        "matched_deal_terms": sorted(set(deal_tm + deal_sm)),
        "matched_fmcg_terms": sorted(set(fmcg_tm + fmcg_sm)),
    }


def _match_domain(domain, publisher, tier_domains):
    d = (domain or "").lower()
    p = (publisher or "").lower()
    for td in tier_domains:
        if d.endswith(td):
            return True
        name = td.split(".")[0]
        if name and name in p:
            return True
    return False


def source_credibility(domain, publisher=""):
    for key, tier in config.CREDIBILITY_TIERS.items():
        if _match_domain(domain, publisher, tier["domains"]):
            return {
                "score": tier["score"],
                "tier": key,
                "label": tier["label"],
                "is_press_release": key == "press_release",
            }
    return {
        "score": config.DEFAULT_CREDIBILITY["score"],
        "tier": "unknown",
        "label": config.DEFAULT_CREDIBILITY["label"],
        "is_press_release": False,
    }


def score_credibility(article):
    base = source_credibility(article.get("source_domain", ""), article.get("publisher", ""))
    corroboration = max(0, len(article.get("corroborating_sources", [])) - 1)

    score = base["score"]
    score += min(corroboration * 4, 12)
    if base["is_press_release"] and corroboration == 0:
        score -= 8
    score = max(0, min(100, score))

    return {
        "credibility": score,
        "credibility_tier": base["tier"],
        "credibility_label": base["label"],
        "is_press_release": base["is_press_release"],
        "corroboration_count": corroboration,
    }


_MONEY_RE = re.compile(
    r"(?:US)?\s?([$€£])\s?(\d[\d,]*(?:\.\d+)?)\s?(billion|bn|million|mn|m|b)\b",
    re.IGNORECASE,
)

_DEAL_TYPE_PATTERNS = [
    ("Acquisition",   r"acqui|snaps up|scoops up|to buy|agrees to buy|takeover|bought"),
    ("Merger",        r"\bmerg"),
    ("Divestiture",   r"divest|sells (?:unit|business|brand|stake)|carve.?out|spin.?off|spinoff"),
    ("Buyout / PE",   r"buyout|leveraged buyout|\blbo\b|private equity"),
    ("Investment",    r"invest|stake|backs|backed by"),
    ("Funding round", r"funding round|series [a-d]\b|raises|raised|venture round"),
    ("IPO",           r"\bipo\b|public offering"),
]

_PARTY_RE = re.compile(
    r"([A-Z][\w&.\-']+(?:\s+[A-Z][\w&.\-']+){0,3})\s+"
    r"(?:to\s+)?(?:acquires?|acquire|buys?|to buy|agrees to buy|merges? with|"
    r"invests? in|takes? over|snaps up|scoops up)\s+"
    r"([A-Z][\w&.\-']+(?:\s+[A-Z][\w&.\-']+){0,3})",
)


def extract_deal_facts(article):
    text = f"{article.get('title', '')}. {article.get('summary', '')}"

    value = None
    m = _MONEY_RE.search(text)
    if m:
        unit = m.group(3).lower()
        scale = "billion" if unit in ("billion", "bn", "b") else "million"
        value = f"{m.group(1)}{m.group(2)} {scale}"

    deal_type = "Deal / other"
    low = text.lower()
    for label, pat in _DEAL_TYPE_PATTERNS:
        if re.search(pat, low):
            deal_type = label
            break

    acquirer = target = None
    pm = _PARTY_RE.search(article.get("title", "") + ". " + article.get("summary", ""))
    if pm:
        acquirer, target = pm.group(1).strip(), pm.group(2).strip()

    return {"deal_value": value, "deal_type": deal_type, "acquirer": acquirer, "target": target}


def _recency_score(dt, lookback_days):
    if dt is None:
        return 0.4
    age_days = (datetime.now(timezone.utc) - dt).total_seconds() / 86400
    return max(0.0, 1.0 - age_days / max(lookback_days, 1))


def composite_rank(article, lookback_days):
    w = config.RANK_WEIGHTS
    rec = _recency_score(article.get("published_dt"), lookback_days)
    corr = min(article.get("corroboration_count", 0) / 4.0, 1.0)
    return (
        w["relevance"] * (article.get("relevance", 0) / 100.0)
        + w["credibility"] * (article.get("credibility", 0) / 100.0)
        + w["recency"] * rec
        + w["corroboration"] * corr
    )


def score_all(articles, lookback_days=None):
    lookback_days = lookback_days or config.THRESHOLDS["lookback_days"]
    for art in articles:
        art.update(score_relevance(art))
        art.update(score_credibility(art))
        art.update(extract_deal_facts(art))
        art["rank_score"] = round(composite_rank(art, lookback_days), 4)
    articles.sort(key=lambda a: a["rank_score"], reverse=True)
    return articles
