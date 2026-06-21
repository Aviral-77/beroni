import os
import re
from datetime import datetime, timezone

from . import config

LLM_MODEL = os.environ.get("FMCG_LLM_MODEL", "")
_WS = re.compile(r"\s+")


def _clean_blurb(text, limit=320):
    text = _WS.sub(" ", text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


def _template_summary(art):
    blurb = _clean_blurb(art.get("summary") or "")
    if blurb:
        return blurb
    if art.get("acquirer") and art.get("target"):
        verb = {
            "Acquisition": "is acquiring", "Merger": "is merging with",
            "Investment": "is investing in", "Divestiture": "is divesting",
        }.get(art.get("deal_type"), "has agreed a deal with")
        sentence = f"{art['acquirer']} {verb} {art['target']}"
        if art.get("deal_value"):
            sentence += f" in a deal valued at {art['deal_value']}"
        return sentence + "."
    return _clean_blurb(art.get("title", ""))


def _llm_summaries(lead_articles):
    api_key = os.environ.get("LLM_API_KEY")
    if not api_key or not LLM_MODEL:
        return None
    try:
        import anthropic
    except Exception:
        return None

    items = []
    for i, art in enumerate(lead_articles):
        items.append(
            f"[{i}] HEADLINE: {art.get('title','')}\n"
            f"    PUBLISHER: {art.get('publisher','')}\n"
            f"    DEAL_TYPE: {art.get('deal_type','')}\n"
            f"    VALUE: {art.get('deal_value') or 'n/a'}\n"
            f"    PARTIES: {art.get('acquirer') or '?'} -> {art.get('target') or '?'}\n"
            f"    BLURB: {_clean_blurb(art.get('summary',''), 400)}"
        )

    system = (
        "You are an FMCG M&A analyst writing a concise weekly intelligence newsletter. "
        "Write in a neutral, factual style. Never invent facts not in the provided material."
    )
    user = (
        "For each item below, write a 1-2 sentence summary (max ~45 words) a business "
        "reader can skim. Then write a 2-3 sentence editor's intro for the whole edition.\n\n"
        'Return STRICT JSON: {"summaries": {"0": "...", "1": "..."}, "intro": "..."}\n\n'
        f"ITEMS:\n" + "\n\n".join(items)
    )

    try:
        import json
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=LLM_MODEL, max_tokens=2000,
            system=system, messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        match = re.search(r"\{.*\}", text, re.DOTALL)
        data = json.loads(match.group(0) if match else text)
        summaries = {
            lead_articles[int(k)]["id"]: v
            for k, v in data.get("summaries", {}).items()
            if k.isdigit() and int(k) < len(lead_articles)
        }
        return summaries, data.get("intro")
    except Exception:
        return None


def _project(art, summary):
    return {
        "id": art["id"],
        "title": art.get("title", ""),
        "summary": summary,
        "deal_type": art.get("deal_type"),
        "deal_value": art.get("deal_value"),
        "acquirer": art.get("acquirer"),
        "target": art.get("target"),
        "publisher": art.get("publisher"),
        "url": art.get("url"),
        "published": art.get("published", ""),
        "credibility": art.get("credibility"),
        "credibility_tier": art.get("credibility_tier"),
        "credibility_label": art.get("credibility_label"),
        "corroboration_count": art.get("corroboration_count", 0),
        "relevance": art.get("relevance"),
    }


def build_newsletter(scored, stage_stats=None, lookback_days=None, use_llm=True):
    lookback_days = lookback_days or config.THRESHOLDS["lookback_days"]
    relevant = [
        a for a in scored
        if a.get("is_relevant") and a.get("relevance", 0) >= config.THRESHOLDS["min_relevance"]
    ]

    n_lead = config.THRESHOLDS["lead_deals"]
    n_brief = config.THRESHOLDS["brief_mentions"]
    lead = relevant[:n_lead]
    brief = relevant[n_lead:n_lead + n_brief]

    llm_used = False
    llm_result = _llm_summaries(lead) if (use_llm and lead) else None
    llm_summaries_map, llm_intro = (llm_result if llm_result else ({}, None))
    if llm_result:
        llm_used = True

    lead_items = [
        _project(a, llm_summaries_map.get(a["id"]) or _template_summary(a))
        for a in lead
    ]
    brief_items = [_project(a, _template_summary(a)) for a in brief]

    now = datetime.now(timezone.utc)
    stage_stats = stage_stats or {}

    total_value_deals = sum(1 for a in relevant if a.get("deal_value"))
    type_counts = {}
    for a in relevant:
        k = a.get("deal_type", "Other")
        type_counts[k] = type_counts.get(k, 0) + 1
    top_types = ", ".join(
        f"{k} ({v})" for k, v in sorted(type_counts.items(), key=lambda x: -x[1])[:4]
    )

    stats_lines = [
        f"{len(relevant)} relevant FMCG deals from {stage_stats.get('ingested', len(scored))} raw articles",
        f"{stage_stats.get('duplicates_removed', 0)} duplicate reports merged",
        f"{total_value_deals} deals with a disclosed value",
        f"Deal mix - {top_types}" if top_types else "",
    ]
    stats_lines = [s for s in stats_lines if s]

    intro = llm_intro or (
        f"This edition tracks {len(relevant)} FMCG deals reported over the last "
        f"{lookback_days} days. Lead stories are ranked by relevance, credibility and recency."
    )

    methodology = [
        f"Ingestion: public RSS/Atom feeds (Google News + FMCG trade press), last {lookback_days} days.",
        f"De-duplication: exact URL/title match, then near-dup clustering by entity overlap "
        f"(threshold {config.THRESHOLDS['near_dup_similarity']}). "
        f"{stage_stats.get('duplicates_removed', 0)} of {stage_stats.get('ingested', 0)} articles merged.",
        f"Relevance: requires a deal signal AND an FMCG signal (title ×2). "
        f"Items below {config.THRESHOLDS['min_relevance']}/100 are dropped.",
        "Credibility: source-tier allow-list + corroboration bonus − lone press-release penalty.",
        "Ranking: relevance 45%, credibility 30%, recency 15%, corroboration 10%.",
        ("Summaries: LLM-generated from sourced material; no facts added."
         if llm_used else
         "Summaries: template from extracted deal facts + source blurb (no LLM_API_KEY set)."),
        "Deal value/parties are regex heuristics and may be incomplete. Decision-support only.",
    ]

    return {
        "title": "FMCG Deal Intelligence",
        "subtitle": f"M&A & investment digest · {now:%d %b %Y} · last {lookback_days} days · {len(relevant)} deals",
        "intro": intro,
        "stats_lines": stats_lines,
        "lead_deals": lead_items,
        "brief_mentions": brief_items,
        "methodology": methodology,
        "generated_at": now.isoformat(),
        "llm_used": llm_used,
        "counts": {
            "ingested": stage_stats.get("ingested"),
            "after_exact_dedup": stage_stats.get("after_exact_dedup"),
            "after_near_dedup": stage_stats.get("after_near_dedup"),
            "relevant": len(relevant),
            "lead": len(lead_items),
            "brief": len(brief_items),
        },
    }


def to_markdown(nl):
    lines = [f"# {nl['title']}", f"*{nl['subtitle']}*", "", nl["intro"], ""]
    if nl["stats_lines"]:
        lines.append("**At a glance**")
        lines += [f"- {s}" for s in nl["stats_lines"]]
        lines.append("")
    lines.append("## Lead deals")
    for i, it in enumerate(nl["lead_deals"], start=1):
        meta = [it.get("deal_type")]
        if it.get("deal_value"):
            meta.append(it["deal_value"])
        parties = " -> ".join(x for x in [it.get("acquirer"), it.get("target")] if x)
        if parties:
            meta.append(parties)
        lines.append(f"### {i}. {it['title']}")
        lines.append("*" + " • ".join(b for b in meta if b) + "*")
        lines.append(it["summary"])
        src_line = (
            f"<sub>Source: {it.get('publisher')} · credibility "
            f"{it.get('credibility')}/100 ({it.get('credibility_tier')})"
        )
        if it.get("corroboration_count"):
            src_line += f" · corroborated by {it['corroboration_count']} other outlet(s)"
        src_line += f" · [link]({it.get('url')})</sub>"
        lines.append(src_line)
        lines.append("")
    if nl["brief_mentions"]:
        lines.append("## Also in the news")
        for it in nl["brief_mentions"]:
            lines.append(f"- **{it['title']}** - {it.get('publisher')} ([link]({it.get('url')}))")
        lines.append("")
    lines.append("---")
    lines.append("### Methodology & assumptions")
    lines += [f"- {m}" for m in nl["methodology"]]
    return "\n".join(lines)
