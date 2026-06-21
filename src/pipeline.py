from dataclasses import dataclass, field

from . import config, ingest, clean, score, newsletter


@dataclass
class PipelineResult:
    articles: list
    newsletter: dict
    stage_stats: dict = field(default_factory=dict)
    fetch_log: list = field(default_factory=list)
    source: str = "live"


def run_pipeline(*, lookback_days=None, min_relevance=None,
                 use_llm=True, sources=None):
    lookback_days = lookback_days if lookback_days is not None else config.THRESHOLDS["lookback_days"]
    if min_relevance is not None:
        config.THRESHOLDS["min_relevance"] = min_relevance

    # Stage 1: Ingest from live feeds only
    articles, fetch_log = ingest.ingest(sources=sources, lookback_days=lookback_days)

    # Stage 2: De-duplicate
    deduped, dedup_stats = clean.deduplicate(articles)

    # Stage 3: Score
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

    # Stage 4: Newsletter
    draft = newsletter.build_newsletter(
        scored, stage_stats=stage_stats, lookback_days=lookback_days, use_llm=use_llm
    )

    return PipelineResult(
        articles=scored,
        newsletter=draft,
        stage_stats=stage_stats,
        fetch_log=fetch_log,
        source="live",
    )
