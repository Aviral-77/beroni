import hashlib
import re
import time
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

try:
    import requests
except Exception:
    requests = None

from . import config

USER_AGENT = "Mozilla/5.0 (compatible; FMCG-Intel-Newsletter/1.0) Python-urllib"
_ATOM = "{http://www.w3.org/2005/Atom}"
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _domain(url):
    try:
        host = urlparse(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def _parse_date(value):
    if not value:
        return None
    value = value.strip()
    try:
        dt = parsedate_to_datetime(value)
        if dt is not None:
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _strip_html(text):
    if not text:
        return ""
    text = _TAG_RE.sub(" ", text)
    text = (
        text.replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')
        .replace("&lt;", "<").replace("&gt;", ">").replace("&nbsp;", " ")
    )
    return _WS_RE.sub(" ", text).strip()


def _mk_id(url, title):
    return hashlib.sha1(f"{url}|{title}".encode("utf-8", "ignore")).hexdigest()[:16]


def _text(el):
    return (el.text or "").strip() if el is not None else ""


def fetch_raw(url, timeout=15):
    if requests is None:
        return None
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, */*"},
            timeout=timeout,
        )
        if resp.status_code == 200 and resp.content:
            return resp.content
    except Exception:
        return None
    return None


def parse_feed(raw, source_name, source_type):
    out = []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return out

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
            src_el = it.find("source")
            pub_source = _text(src_el)
            if src_el is not None and not link:
                link = src_el.get("url", "")

        title = _strip_html(title)
        summary = _strip_html(summary)
        if not title or not link:
            continue

        publisher = pub_source or source_name
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


def ingest(sources=None, lookback_days=None, max_per_feed=None, polite_delay=0.0):
    sources = sources if sources is not None else config.all_sources()
    lookback_days = lookback_days if lookback_days is not None else config.THRESHOLDS["lookback_days"]
    max_per_feed = max_per_feed if max_per_feed is not None else config.THRESHOLDS["max_items_per_feed"]

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    articles = []
    log = []

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
            if dt is not None and dt < cutoff:
                continue
            articles.append(art)
            kept += 1
        log.append({"feed": src["name"], "status": "ok", "count": kept})
        if polite_delay:
            time.sleep(polite_delay)

    return articles, log


def load_sample(path="data/sample_articles.json"):
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
