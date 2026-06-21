"""
Stage 2 — CLEANING & DE-DUPLICATION.

The same deal is typically reported by many outlets (a wire story gets picked
up verbatim, headlines get lightly reworded). We collapse these so the
newsletter shows each *deal* once, while remembering how many independent
outlets covered it (corroboration → a credibility signal later).

Two passes, both dependency-free and fully transparent:

  1. EXACT dedup     — identical normalised URL or normalised title.
  2. NEAR-DUP merge  — fingerprint each story by its named entities (companies,
                       brands) and figures plus significant content words, then
                       merge two reports when they share >= 2 entities AND their
                       blended similarity reaches the threshold, where:
                         similarity = 0.5 * entity_overlap + 0.5 * content_overlap
                         overlap(A, B) = |A ∩ B| / min(|A|, |B|)   (overlap coef)
                       Outlets reword headlines freely but reuse the same company
                       names and figures, so entity overlap is the discriminating
                       signal. Clustering uses a union-find structure so
                       transitively-similar items end up in one group; the cluster
                       keeps the most credible, then most recent item as its
                       representative, and the rest become corroboration.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

from . import config
from .score import source_credibility  # base credibility for choosing a representative

_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")
_TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "mc_", "ref", "cmpid", "ocid")

# Capitalised proper nouns (entities) and monetary/numeric figures are the
# strongest fingerprint of "same story across outlets".
_ENTITY_RE = re.compile(r"\b[A-Z][A-Za-z&.\-']+\b")
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_WORD_RE = re.compile(r"[a-z]{4,}")

# Very common words that add no discriminating power for similarity. Includes
# adjectives/nouns that frequently appear title-cased (sentence-initial or in
# headlines) and would otherwise masquerade as identifying "entities".
_STOP = {
    "the", "a", "an", "to", "of", "in", "on", "for", "and", "or", "with",
    "as", "at", "by", "from", "its", "is", "are", "be", "will", "has", "have",
    "after", "amid", "into", "over", "deal", "says", "said", "new", "maker",
    "brand", "group", "company", "business", "sources", "billion", "million",
    "this", "that", "than", "more", "most", "about", "around", "which",
    "consumer", "goods", "premium", "global", "regional", "national", "city",
    "french", "mexican", "european", "american", "private", "equity", "growth",
    "the", "a", "leading", "major", "fast", "growing",
}


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------
def normalize_url(url: str) -> str:
    """Lowercase host, drop tracking query params and fragments/trailing slash."""
    try:
        p = urlparse(url)
        host = p.netloc.lower()
        host = host[4:] if host.startswith("www.") else host
        q = [(k, v) for k, v in parse_qsl(p.query)
             if not any(k.lower().startswith(pfx) for pfx in _TRACKING_PREFIXES)]
        path = p.path.rstrip("/")
        return urlunparse(("", host, path, "", urlencode(q), ""))
    except Exception:
        return url.strip().lower()


def normalize_title(title: str) -> str:
    """Lowercase, strip a trailing ' - Publisher', remove punctuation/whitespace."""
    t = title or ""
    if " - " in t:                      # drop Google-News style publisher suffix
        head = t.rsplit(" - ", 1)[0]
        if len(head) > 20:              # only if it leaves a meaningful headline
            t = head
    t = _PUNCT_RE.sub(" ", t.lower())
    return _WS_RE.sub(" ", t).strip()


def _fingerprint(title: str, summary: str) -> tuple[frozenset[str], frozenset[str]]:
    """
    Build a story fingerprint from title + summary.

    Returns (entities, content) where:
      entities = lowercased proper-noun tokens + numeric figures (the names and
                 amounts that identify *which deal* this is), and
      content  = entities plus significant content words (≥4 chars, non-stop).
    """
    text = f"{title} {summary}"
    entities = {w.lower() for w in _ENTITY_RE.findall(text)} - _STOP
    entities |= set(_NUM_RE.findall(text))
    content = entities | {w for w in _WORD_RE.findall(text.lower()) if w not in _STOP}
    return frozenset(entities), frozenset(content)


# ---------------------------------------------------------------------------
# Similarity
# ---------------------------------------------------------------------------
def _overlap(a: frozenset[str], b: frozenset[str]) -> float:
    """Overlap coefficient |A∩B| / min(|A|,|B|) — robust to length differences."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def similarity(a: dict, b: dict) -> float:
    """
    Blended near-duplicate similarity in [0, 1]:
      • shared named entities / figures (the deal's fingerprint), and
      • shared significant content,
    each as an overlap coefficient. Different outlets reword headlines freely
    but reuse the same company names, brands and figures — so entity overlap is
    the dominant, discriminating signal.
    """
    ent = _overlap(a["_entities"], b["_entities"])
    content = _overlap(a["_content"], b["_content"])
    return (
        config.THRESHOLDS["entity_weight"] * ent
        + config.THRESHOLDS["content_weight"] * content
    )


# ---------------------------------------------------------------------------
# Union-Find
# ---------------------------------------------------------------------------
class _UF:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def deduplicate(articles: list[dict]) -> tuple[list[dict], dict]:
    """
    Collapse exact and near-duplicate articles.

    Returns (representatives, stats). Each representative gains:
        cluster_size          – number of articles merged into it
        corroborating_sources – sorted list of distinct publisher domains
        duplicate_urls        – the other URLs that reported the same story
    """
    stats = {"ingested": len(articles)}

    # ---- Pass 1: exact dedup on normalised URL, then normalised title -------
    seen_url: dict[str, dict] = {}
    seen_title: dict[str, dict] = {}
    exact_unique: list[dict] = []
    for art in articles:
        nurl = normalize_url(art.get("url", ""))
        ntitle = normalize_title(art.get("title", ""))
        art["_norm_url"], art["_norm_title"] = nurl, ntitle
        if nurl and nurl in seen_url:
            continue
        if ntitle and ntitle in seen_title:
            continue
        seen_url[nurl] = art
        seen_title[ntitle] = art
        ents, content = _fingerprint(art.get("title", ""), art.get("summary", ""))
        art["_entities"], art["_content"] = ents, content
        exact_unique.append(art)
    stats["after_exact_dedup"] = len(exact_unique)

    # ---- Pass 2: near-duplicate clustering ----------------------------------
    n = len(exact_unique)
    uf = _UF(n)
    threshold = config.THRESHOLDS["near_dup_similarity"]
    # O(n^2) pairwise — fine for the hundreds-of-items scale this operates at.
    for i in range(n):
        ai = exact_unique[i]
        for j in range(i + 1, n):
            aj = exact_unique[j]
            # The same deal reported by different outlets shares ≥2 identifying
            # entities/figures (e.g. acquirer + target, or company + amount).
            # A single shared common word is not enough — this guards against
            # merging two unrelated stories that happen to share one term.
            if len(ai["_entities"] & aj["_entities"]) < 2:
                continue
            if similarity(ai, aj) >= threshold:
                uf.union(i, j)

    clusters: dict[int, list[int]] = {}
    for idx in range(n):
        clusters.setdefault(uf.find(idx), []).append(idx)

    representatives: list[dict] = []
    for members in clusters.values():
        arts = [exact_unique[m] for m in members]
        # representative = highest credibility, then most recent
        rep = max(arts, key=lambda a: (
            source_credibility(a.get("source_domain", ""), a.get("publisher", ""))["score"],
            a.get("published_dt") or _min_dt(),
        ))
        domains = sorted({a.get("source_domain") or a.get("publisher", "") for a in arts if (a.get("source_domain") or a.get("publisher"))})
        rep["cluster_size"] = len(arts)
        rep["corroborating_sources"] = domains
        rep["duplicate_urls"] = [a["url"] for a in arts if a["url"] != rep["url"]]
        representatives.append(rep)

    stats["after_near_dedup"] = len(representatives)
    stats["duplicates_removed"] = stats["ingested"] - stats["after_near_dedup"]
    return representatives, stats


def _min_dt():
    from datetime import datetime, timezone
    return datetime.min.replace(tzinfo=timezone.utc)
