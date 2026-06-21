"""
Stage 3 — SCORING.

Three transparent, rule-based scorers (no black boxes):

  • RELEVANCE   — is this actually an FMCG *deal*? Gated on two independent
                  signals (a transaction cue AND a consumer-goods subject cue),
                  so generic business news or non-deal FMCG news scores low.
  • CREDIBILITY — editorial standing of the source (tiered allow-list) plus a
                  corroboration bonus when several independent outlets agree,
                  minus a penalty for un-corroborated press-release wires.
  • DEAL FACTS  — light regex extraction of deal value, type and parties so the
                  newsletter can show structured detail, not just a headline.

All weights/tiers live in config.py and every score is explainable from the
`matched_*` fields we attach to each article.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from . import config


# ---------------------------------------------------------------------------
# RELEVANCE
# ---------------------------------------------------------------------------
def _weighted_hits(text: str, vocab: dict[str, int]) -> tuple[int, list[str]]:
    """Sum weights of vocabulary terms present in text; return (score, matches)."""
    total, matched = 0, []
    for term, weight in vocab.items():
        if term in text:
            total += weight
            matched.append(term)
    return total, matched


def score_relevance(article: dict) -> dict:
    """
    Relevance in [0, 100], gated on BOTH a deal signal and an FMCG signal.

    Title matches count double (headlines are the strongest cue). The two
    signals are normalised and blended; if either signal is absent the item is
    marked not-relevant and its score is heavily capped.
    """
    title = (article.get("title") or "").lower()
    summary = (article.get("summary") or "").lower()

    deal_t, deal_tm = _weighted_hits(title, config.DEAL_KEYWORDS)
    deal_s, deal_sm = _weighted_hits(summary, config.DEAL_KEYWORDS)
    fmcg_vocab = {**config.FMCG_CATEGORY_KEYWORDS, **config.FMCG_COMPANY_KEYWORDS}
    fmcg_t, fmcg_tm = _weighted_hits(title, fmcg_vocab)
    fmcg_s, fmcg_sm = _weighted_hits(summary, fmcg_vocab)

    deal_signal = deal_t * 2 + deal_s          # title weighted x2
    fmcg_signal = fmcg_t * 2 + fmcg_s

    has_deal = deal_signal > 0
    has_fmcg = fmcg_signal > 0
    is_relevant = has_deal and has_fmcg

    # Normalise each signal to ~[0,1] with a soft cap, then blend.
    norm_deal = min(deal_signal, 10) / 10.0
    norm_fmcg = min(fmcg_signal, 10) / 10.0
    blended = 0.55 * norm_deal + 0.45 * norm_fmcg
    score = round(100 * blended)

    if not is_relevant:
        # Missing one of the two required signals → cap hard so it's filtered out.
        score = min(score, 20)

    return {
        "relevance": score,
        "is_relevant": is_relevant,
        "deal_signal": deal_signal,
        "fmcg_signal": fmcg_signal,
        "matched_deal_terms": sorted(set(deal_tm + deal_sm)),
        "matched_fmcg_terms": sorted(set(fmcg_tm + fmcg_sm)),
    }


# ---------------------------------------------------------------------------
# CREDIBILITY
# ---------------------------------------------------------------------------
def _match_domain(domain: str, publisher: str, tier_domains: list[str]) -> bool:
    d = (domain or "").lower()
    p = (publisher or "").lower()
    for td in tier_domains:
        if d.endswith(td):
            return True
        # also match by publisher name token (Google News gives names, not domains)
        name = td.split(".")[0]
        if name and name in p:
            return True
    return False


def source_credibility(domain: str, publisher: str = "") -> dict:
    """Base credibility purely from the source's tier (no corroboration here)."""
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


def score_credibility(article: dict) -> dict:
    """
    Final credibility in [0, 100] = base source tier
        + corroboration bonus (independent outlets reporting the same story)
        − penalty for an un-corroborated press-release wire.
    """
    base = source_credibility(article.get("source_domain", ""), article.get("publisher", ""))
    corroboration = max(0, len(article.get("corroborating_sources", [])) - 1)

    score = base["score"]
    # Each extra independent outlet adds confidence, capped at +12.
    score += min(corroboration * 4, 12)
    # A lone press release (nobody else picked it up) loses a little trust.
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


# ---------------------------------------------------------------------------
# DEAL-FACT EXTRACTION
# ---------------------------------------------------------------------------
_MONEY_RE = re.compile(
    r"(?:US)?\s?([$€£])\s?(\d[\d,]*(?:\.\d+)?)\s?(billion|bn|million|mn|m|b)\b",
    re.IGNORECASE,
)

_DEAL_TYPE_PATTERNS = [
    ("Acquisition",  r"acqui|snaps up|scoops up|to buy|agrees to buy|takeover|bought"),
    ("Merger",       r"\bmerg"),
    ("Divestiture",  r"divest|sells (?:unit|business|brand|stake)|carve.?out|spin.?off|spinoff"),
    ("Buyout / PE",  r"buyout|leveraged buyout|\blbo\b|private equity"),
    ("Investment",   r"invest|stake|backs|backed by"),
    ("Funding round", r"funding round|series [a-d]\b|raises|raised|venture round"),
    ("IPO",          r"\bipo\b|public offering"),
]

_PARTY_RE = re.compile(
    r"([A-Z][\w&.\-']+(?:\s+[A-Z][\w&.\-']+){0,3})\s+"
    r"(?:to\s+)?(?:acquires?|acquire|buys?|to buy|agrees to buy|merges? with|"
    r"invests? in|takes? over|snaps up|scoops up)\s+"
    r"([A-Z][\w&.\-']+(?:\s+[A-Z][\w&.\-']+){0,3})",
)


def _normalize_value(symbol: str, amount: str, unit: str) -> str:
    unit = unit.lower()
    scale = "billion" if unit in ("billion", "bn", "b") else "million"
    return f"{symbol}{amount} {scale}"


def extract_deal_facts(article: dict) -> dict:
    """Best-effort structured facts from the headline + summary (regex heuristics)."""
    text = f"{article.get('title','')}. {article.get('summary','')}"

    # Deal value
    value = None
    m = _MONEY_RE.search(text)
    if m:
        value = _normalize_value(m.group(1), m.group(2), m.group(3))

    # Deal type
    deal_type = "Deal / other"
    low = text.lower()
    for label, pat in _DEAL_TYPE_PATTERNS:
        if re.search(pat, low):
            deal_type = label
            break

    # Parties (acquirer / target)
    acquirer = target = None
    pm = _PARTY_RE.search(article.get("title", "") + ". " + article.get("summary", ""))
    if pm:
        acquirer, target = pm.group(1).strip(), pm.group(2).strip()

    return {
        "deal_value": value,
        "deal_type": deal_type,
        "acquirer": acquirer,
        "target": target,
    }


# ---------------------------------------------------------------------------
# Composite ranking + orchestration over a list
# ---------------------------------------------------------------------------
def _recency_score(dt: datetime | None, lookback_days: int) -> float:
    if dt is None:
        return 0.4  # undated → neutral-ish
    age_days = (datetime.now(timezone.utc) - dt).total_seconds() / 86400
    return max(0.0, 1.0 - age_days / max(lookback_days, 1))


def composite_rank(article: dict, lookback_days: int) -> float:
    w = config.RANK_WEIGHTS
    rec = _recency_score(article.get("published_dt"), lookback_days)
    corr = min(article.get("corroboration_count", 0) / 4.0, 1.0)
    return (
        w["relevance"] * (article.get("relevance", 0) / 100.0)
        + w["credibility"] * (article.get("credibility", 0) / 100.0)
        + w["recency"] * rec
        + w["corroboration"] * corr
    )


def score_all(articles: list[dict], lookback_days: int | None = None) -> list[dict]:
    """Apply all scorers and the composite rank to every article in place."""
    lookback_days = lookback_days or config.THRESHOLDS["lookback_days"]
    for art in articles:
        art.update(score_relevance(art))
        art.update(score_credibility(art))
        art.update(extract_deal_facts(art))
        art["rank_score"] = round(composite_rank(art, lookback_days), 4)
    articles.sort(key=lambda a: a["rank_score"], reverse=True)
    return articles
