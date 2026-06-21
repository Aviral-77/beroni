"""
Stage 1 — INGESTION.

Pulls deal-related news from public RSS/Atom feeds (Google News queries +
trade-press feeds) and normalises every item into a flat `Article` dict.

We deliberately avoid the `feedparser` dependency (it drags in a legacy
`sgmllib3k` package that fails to build in some sandboxes). Instead we parse
with the standard library `xml.etree.ElementTree`, which handles both RSS 2.0
and Atom once namespaces are accounted for.
"""

from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

try:
    import requests
except Exception:  # pragma: no cover - requests is in requirements
    requests = None

from . import config

USER_AGENT = (
    "Mozilla/5.0 (compatible; FMCG-Intel-Newsletter/1.0; "
    "+https://github.com/) Python-urllib"
)

# Atom namespace (RSS 2.0 uses no namespace for the elements we read)
_ATOM = "{http://www.w3.org/2005/Atom}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def _parse_date(value: str | None) -> datetime | None:
    """Parse RFC-822 (RSS) or ISO-8601 (Atom) dates -> aware UTC datetime."""
    if not value:
        return None
    value = value.strip()
    # RFC-822, e.g. "Tue, 17 Jun 2025 09:30:00 GMT"
    try:
        dt = parsedate_to_datetime(value)
        if dt is not None:
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    # ISO-8601, e.g. "2025-06-17T09:30:00Z"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip_html(text: str | None) -> str:
    if not text:
        return ""
    text = _TAG_RE.sub(" ", text)
    text = (
        text.replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')
        .replace("&lt;", "<").replace("&gt;", ">").replace("&nbsp;", " ")
    )
    return _WS_RE.sub(" ", text).strip()


def _mk_id(url: str, title: str) -> str:
    return hashlib.sha1(f"{url}|{title}".encode("utf-8", "ignore")).hexdigest()[:16]


def _text(el) -> str:
    return (el.text or "").strip() if el is not None else ""


# ---------------------------------------------------------------------------
# Feed fetching / parsing
# ---------------------------------------------------------------------------
def fetch_raw(url: str, timeout: int = 15) -> bytes | None:
    """Fetch a feed URL, returning raw bytes (or None on failure)."""
    if requests is None:
        return None
    try:
        resp = requests.get(
            url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml, */*"},
            timeout=timeout,
        )
        if resp.status_code == 200 and resp.content:
            return resp.content
    except Exception:
        return None
    return None


def parse_feed(raw: bytes, source_name: str, source_type: str) -> list[dict]:
    """Parse raw RSS/Atom bytes into a list of normalised article dicts."""
    out: list[dict] = []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return out

    # RSS 2.0: <rss><channel><item>...   |   Atom: <feed><entry>...
    items = root.findall(".//item")
    is_atom = False
    if not items:
        items = root.findall(f".//{_ATOM}entry")
        is_atom = True

    for it in items:
        if is_atom:
            title = _text(it.find(f"{_ATOM}title"))
            link_el = it.find(f"{_ATOM}link")
            link = link_el.get("href") if link_el is not None else ""
            summary = _text(it.find(f"{_ATOM}summary")) or _text(it.find(f"{_ATOM}content"))
            published = _text(it.find(f"{_ATOM}updated")) or _text(it.find(f"{_ATOM}published"))
            pub_source = ""
        else:
            title = _text(it.find("title"))
            link = _text(it.find("link"))
            summary = _text(it.find("description"))
            published = _text(it.find("pubDate"))
            # Google News embeds the real publisher in <source url="...">Name</source>
            src_el = it.find("source")
            pub_source = _text(src_el)
            if src_el is not None and not link:
                link = src_el.get("url", "")

        title = _strip_html(title)
        summary = _strip_html(summary)
        if not title or not link:
            continue

        # For Google News, the original publisher is the <source>, otherwise the feed
        publisher = pub_source or source_name
        # Google News titles often end with " - Publisher"; capture that too
        if source_type == "google_news" and not pub_source and " - " in title:
            publisher = title.rsplit(" - ", 1)[-1].strip()

        out.append({
            "id": _mk_id(link, title),
            "title": title,
            "summary": summary,
            "url": link,
            "publisher": publisher,
            "source_domain": _domain(link),
            "feed": source_name,
            "published_raw": published,
        })
    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def ingest(
    sources: list[dict] | None = None,
    lookback_days: int | None = None,
    max_per_feed: int | None = None,
    polite_delay: float = 0.0,
) -> tuple[list[dict], list[dict]]:
    """
    Fetch and normalise articles from all configured sources.

    Returns (articles, fetch_log) where fetch_log records per-feed outcomes so
    the UI can show exactly what was reached and what was blocked.
    """
    sources = sources if sources is not None else config.all_sources()
    lookback_days = lookback_days if lookback_days is not None else config.THRESHOLDS["lookback_days"]
    max_per_feed = max_per_feed if max_per_feed is not None else config.THRESHOLDS["max_items_per_feed"]

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    articles: list[dict] = []
    log: list[dict] = []

    for src in sources:
        raw = fetch_raw(src["url"])
        if raw is None:
            log.append({"feed": src["name"], "status": "unreachable", "count": 0})
            continue

        parsed = parse_feed(raw, src["name"], src.get("type", "rss"))
        kept = 0
        for art in parsed[:max_per_feed]:
            dt = _parse_date(art["published_raw"])
            art["published_dt"] = dt
            art["published"] = dt.isoformat() if dt else ""
            # Keep undated items (some trade feeds omit dates) but drop clearly old ones
            if dt is not None and dt < cutoff:
                continue
            articles.append(art)
            kept += 1
        log.append({"feed": src["name"], "status": "ok", "count": kept})
        if polite_delay:
            time.sleep(polite_delay)

    return articles, log


def load_sample(path: str = "data/sample_articles.json") -> tuple[list[dict], list[dict]]:
    """
    Load the bundled illustrative dataset (used when live feeds are blocked,
    e.g. in a restricted sandbox, so the demo always has something to show).
    """
    import json
    import os

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    full = os.path.join(here, path)
    with open(full, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    for art in data:
        art.setdefault("id", _mk_id(art.get("url", ""), art.get("title", "")))
        art.setdefault("source_domain", _domain(art.get("url", "")))
        art.setdefault("feed", "sample")
        dt = _parse_date(art.get("published"))
        art["published_dt"] = dt
        art["published"] = dt.isoformat() if dt else art.get("published", "")
    log = [{"feed": "bundled sample dataset", "status": "sample", "count": len(data)}]
    return data, log
