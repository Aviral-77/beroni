"""
The AGENT — pipeline orchestration.

A single, linear, inspectable flow:

    ingest → clean (de-dup) → score (relevance + credibility) → newsletter

`run_pipeline` returns a `PipelineResult` carrying every intermediate output
and a per-stage funnel log, so the Streamlit app and the CLI can show exactly
what happened at each step (and so the logic is easy to reason about / test).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import config, ingest, clean, score, newsletter


@dataclass
class PipelineResult:
    articles: list[dict]               # final scored + ranked articles
    newsletter: dict                   # structured newsletter draft
    stage_stats: dict = field(default_factory=dict)   # funnel counts
    fetch_log: list[dict] = field(default_factory=list)  # per-feed outcomes
    source: str = "live"               # "live" or "sample"


def run_pipeline(
    *,
    use_live: bool = True,
    lookback_days: int | None = None,
    min_relevance: int | None = None,
    use_llm: bool = True,
    sources: list[dict] | None = None,
    fallback_to_sample: bool = True,
) -> PipelineResult:
    """
    Execute the full ingestion → newsletter pipeline.

    use_live=False (or a live fetch that returns nothing, with
    fallback_to_sample=True) uses the bundled illustrative dataset so the demo
    always produces output even when outbound news access is blocked.
    """
    lookback_days = lookback_days if lookback_days is not None else config.THRESHOLDS["lookback_days"]
    if min_relevance is not None:
        config.THRESHOLDS["min_relevance"] = min_relevance

    # ---- Stage 1: INGEST ----------------------------------------------------
    source = "live"
    if use_live:
        articles, fetch_log = ingest.ingest(sources=sources, lookback_days=lookback_days)
        if not articles and fallback_to_sample:
            # Preserve the live-attempt log so the UI can show what was blocked,
            # then append the sample dataset's own log line.
            sample_articles, sample_log = ingest.load_sample()
            articles, fetch_log = sample_articles, fetch_log + sample_log
            source = "sample"
    else:
        articles, fetch_log = ingest.load_sample()
        source = "sample"

    # ---- Stage 2: CLEAN / DE-DUPLICATE -------------------------------------
    deduped, dedup_stats = clean.deduplicate(articles)

    # ---- Stage 3: SCORE -----------------------------------------------------
    scored = score.score_all(deduped, lookback_days=lookback_days)

    relevant_n = sum(
        1 for a in scored
        if a.get("is_relevant") and a.get("relevance", 0) >= config.THRESHOLDS["min_relevance"]
    )
    stage_stats = {
        **dedup_stats,
        "relevant": relevant_n,
        "filtered_out": dedup_stats["after_near_dedup"] - relevant_n,
    }

    # ---- Stage 4: NEWSLETTER ------------------------------------------------
    draft = newsletter.build_newsletter(
        scored, stage_stats=stage_stats, lookback_days=lookback_days, use_llm=use_llm
    )

    return PipelineResult(
        articles=scored,
        newsletter=draft,
        stage_stats=stage_stats,
        fetch_log=fetch_log,
        source=source,
    )
