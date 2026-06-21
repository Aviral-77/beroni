"""
Stage 4 — NEWSLETTER.

Turns the scored, de-duplicated article list into a short, structured draft a
business reader can skim: a lead section of the most important deals, a
"also in the news" tail, an at-a-glance intro, and a transparent methodology
footer.

Summaries are written two ways:
  • TEMPLATE (default, zero dependencies, always works offline) — cleans and
    truncates the source blurb and prepends the structured facts we extracted.
  • LLM (optional) — if ANTHROPIC_API_KEY is set and the `anthropic` SDK is
    installed, Claude writes a crisp one-to-two sentence analyst summary per
    lead deal and a short editor's intro. Falls back to TEMPLATE on any error.

This keeps the demo fully functional with no credentials, while showing the
"agent writes the newsletter" capability when a key is available.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone

from . import config

# Default to the latest, most capable Claude model; override with FMCG_LLM_MODEL.
LLM_MODEL = os.environ.get("FMCG_LLM_MODEL", "claude-opus-4-8")

_WS = re.compile(r"\s+")


def _clean_blurb(text: str, limit: int = 320) -> str:
    text = _WS.sub(" ", text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut + "…"


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------
def _template_summary(art: dict) -> str:
    """
    Extractive, dependency-free summary.

    The structured facts (deal type, value, parties) are surfaced separately in
    the newsletter's meta line / spreadsheet columns, so the summary itself is
    just the cleaned source blurb. When no blurb is available we synthesise a
    one-liner from the extracted facts instead.
    """
    blurb = _clean_blurb(art.get("summary") or "")
    if blurb:
        return blurb

    # Fallback: no usable blurb — build a sentence from what we extracted.
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


def _llm_summaries(lead_articles: list[dict]) -> tuple[dict[str, str], str | None] | None:
    """
    Use Claude to write per-deal summaries + an intro.

    Returns ({article_id: summary}, intro_text) or None if the LLM path is
    unavailable / fails (callers fall back to the template path).
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
    except Exception:
        return None

    # Build a compact, factual brief for the model (titles + blurbs + facts only).
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
    brief = "\n\n".join(items)

    system = (
        "You are an FMCG (fast-moving consumer goods) M&A analyst writing a "
        "concise weekly intelligence newsletter for busy business readers. "
        "Write in a neutral, factual, broadsheet-business style. Never invent "
        "facts, figures, or parties not present in the provided material. If a "
        "detail is not given, omit it rather than guessing."
    )
    user = (
        "Below are the lead FMCG deal stories for this edition. For EACH item, "
        "write a single crisp summary of 1-2 sentences (max ~45 words) that a "
        "business reader can skim to understand what happened and why it matters. "
        "Then write a 2-3 sentence editor's intro for the whole edition.\n\n"
        "Return STRICT JSON of the form:\n"
        '{"summaries": {"0": "...", "1": "..."}, "intro": "..."}\n\n'
        f"ITEMS:\n{brief}"
    )

    try:
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=LLM_MODEL,
            max_tokens=2000,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        # The model may wrap JSON in prose/fences; extract the first {...} block.
        import json
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


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------
def _project(art: dict, summary: str) -> dict:
    """Pull just the fields the newsletter / exporters need from an article."""
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


def build_newsletter(
    scored: list[dict],
    stage_stats: dict | None = None,
    lookback_days: int | None = None,
    use_llm: bool = True,
) -> dict:
    """
    Assemble the structured newsletter dict consumed by the app and exporters.
    `scored` must already be ranked (see score.score_all).
    """
    lookback_days = lookback_days or config.THRESHOLDS["lookback_days"]
    relevant = [a for a in scored if a.get("is_relevant") and a.get("relevance", 0) >= config.THRESHOLDS["min_relevance"]]

    n_lead = config.THRESHOLDS["lead_deals"]
    n_brief = config.THRESHOLDS["brief_mentions"]
    lead = relevant[:n_lead]
    brief = relevant[n_lead:n_lead + n_brief]

    # --- summaries (LLM if available, else template) ------------------------
    llm_used = False
    llm_result = _llm_summaries(lead) if (use_llm and lead) else None
    llm_summaries, llm_intro = (llm_result if llm_result else ({}, None))
    if llm_result:
        llm_used = True

    lead_items = [
        _project(a, llm_summaries.get(a["id"]) or _template_summary(a))
        for a in lead
    ]
    brief_items = [_project(a, _template_summary(a)) for a in brief]

    # --- headline stats ------------------------------------------------------
    now = datetime.now(timezone.utc)
    total_value_deals = sum(1 for a in relevant if a.get("deal_value"))
    type_counts: dict[str, int] = {}
    for a in relevant:
        type_counts[a.get("deal_type", "Other")] = type_counts.get(a.get("deal_type", "Other"), 0) + 1
    top_types = ", ".join(f"{k} ({v})" for k, v in sorted(type_counts.items(), key=lambda x: -x[1])[:4])

    stage_stats = stage_stats or {}
    stats_lines = [
        f"{len(relevant)} relevant FMCG deals surfaced from "
        f"{stage_stats.get('ingested', len(scored))} raw articles",
        f"{stage_stats.get('duplicates_removed', 0)} duplicate/near-duplicate reports merged",
        f"{total_value_deals} deals with a disclosed value",
        f"Deal mix — {top_types}" if top_types else "",
    ]
    stats_lines = [s for s in stats_lines if s]

    intro = llm_intro or (
        f"This edition tracks {len(relevant)} fast-moving consumer goods "
        f"deals reported over the last {lookback_days} days. "
        f"The lead stories below are ranked by a blend of relevance, source "
        f"credibility and recency; a longer tail of smaller moves follows."
    )

    title = "FMCG Deal Intelligence"
    subtitle = (
        f"M&A & investment digest · {now:%d %b %Y} · "
        f"last {lookback_days} days · {len(relevant)} deals"
    )

    methodology = _methodology_lines(stage_stats, llm_used, lookback_days)

    return {
        "title": title,
        "subtitle": subtitle,
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


def to_markdown(nl: dict) -> str:
    """Render the newsletter as Markdown (used for the in-app preview)."""
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
        parties = " → ".join(x for x in [it.get("acquirer"), it.get("target")] if x)
        if parties:
            meta.append(parties)
        lines.append(f"### {i}. {it['title']}")
        lines.append("*" + " • ".join(b for b in meta if b) + "*")
        lines.append(it["summary"])
        lines.append(
            f"<sub>Source: {it.get('publisher')} · credibility "
            f"{it.get('credibility')}/100 ({it.get('credibility_tier')})"
            + (f" · corroborated by {it.get('corroboration_count')} other outlet(s)"
               if it.get("corroboration_count") else "")
            + f" · [link]({it.get('url')})</sub>"
        )
        lines.append("")
    if nl["brief_mentions"]:
        lines.append("## Also in the news")
        for it in nl["brief_mentions"]:
            lines.append(f"- **{it['title']}** — {it.get('publisher')} ([link]({it.get('url')}))")
        lines.append("")
    lines.append("---")
    lines.append("### Methodology & assumptions")
    lines += [f"- {m}" for m in nl["methodology"]]
    return "\n".join(lines)


def _methodology_lines(stats: dict, llm_used: bool, lookback_days: int) -> list[str]:
    return [
        f"Ingestion: public RSS/Atom feeds (Google News deal queries + FMCG trade press), "
        f"filtered to the last {lookback_days} days. No paywalled or private sources.",
        f"De-duplication: exact match on normalised URL/title, then near-duplicate clustering. "
        f"Each story is fingerprinted by its named entities (companies, brands) and figures plus "
        f"significant content words; two reports merge when they share at least 2 entities AND "
        f"their blended overlap (entity + content overlap coefficients) reaches "
        f"{config.THRESHOLDS['near_dup_similarity']:.2f}. The most credible/recent report is kept "
        f"as the representative. {stats.get('duplicates_removed', 0)} of {stats.get('ingested', 0)} "
        f"articles merged this run.",
        "Relevance: an item must show BOTH a deal signal (acquire/merger/stake/funding…) and an "
        "FMCG signal (category or named consumer-goods company); title matches weighted x2. "
        f"Items scoring below {config.THRESHOLDS['min_relevance']}/100 are dropped from the draft.",
        "Credibility: transparent source-tier allow-list (global wire > trade press > general > "
        "press-release wires), plus a corroboration bonus when multiple independent outlets report "
        "the same deal, and a penalty for lone press releases. We rate the SOURCE, not each claim.",
        "Ranking: composite of relevance (45%), credibility (30%), recency (15%) and corroboration (10%).",
        ("Summaries: written by Claude (" + LLM_MODEL + ") from the sourced material; no facts added."
         if llm_used else
         "Summaries: template-generated from extracted deal facts + the source blurb (no LLM key set)."),
        "Assumptions & limits: deal value/parties are extracted heuristically (regex) and may be "
        "incomplete; coverage reflects what public feeds surface; this is decision-support, not advice.",
    ]
