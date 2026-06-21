import re
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

from . import config
from .score import source_credibility

_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")
_TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "mc_", "ref", "cmpid", "ocid")

_ENTITY_RE = re.compile(r"\b[A-Z][A-Za-z&.\-']+\b")
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_WORD_RE = re.compile(r"[a-z]{4,}")

# Common words that would otherwise appear as "entities" in capitalised headlines
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


def normalize_url(url):
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


def normalize_title(title):
    t = title or ""
    if " - " in t:
        head = t.rsplit(" - ", 1)[0]
        if len(head) > 20:
            t = head
    t = _PUNCT_RE.sub(" ", t.lower())
    return _WS_RE.sub(" ", t).strip()


def _fingerprint(title, summary):
    text = f"{title} {summary}"
    entities = {w.lower() for w in _ENTITY_RE.findall(text)} - _STOP
    entities |= set(_NUM_RE.findall(text))
    content = entities | {w for w in _WORD_RE.findall(text.lower()) if w not in _STOP}
    return frozenset(entities), frozenset(content)


def _overlap(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def similarity(a, b):
    ent = _overlap(a["_entities"], b["_entities"])
    content = _overlap(a["_content"], b["_content"])
    return (
        config.THRESHOLDS["entity_weight"] * ent
        + config.THRESHOLDS["content_weight"] * content
    )


class _UF:
    def __init__(self, n):
        self.parent = list(range(n))

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def deduplicate(articles):
    stats = {"ingested": len(articles)}

    # Pass 1: exact dedup on normalised URL then normalised title
    seen_url = {}
    seen_title = {}
    exact_unique = []
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

    # Pass 2: near-duplicate clustering via entity-overlap fingerprinting
    n = len(exact_unique)
    uf = _UF(n)
    threshold = config.THRESHOLDS["near_dup_similarity"]
    for i in range(n):
        ai = exact_unique[i]
        for j in range(i + 1, n):
            aj = exact_unique[j]
            # Require at least 2 shared entities - a single shared word isn't enough
            if len(ai["_entities"] & aj["_entities"]) < 2:
                continue
            if similarity(ai, aj) >= threshold:
                uf.union(i, j)

    clusters = {}
    for idx in range(n):
        clusters.setdefault(uf.find(idx), []).append(idx)

    representatives = []
    for members in clusters.values():
        arts = [exact_unique[m] for m in members]
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
