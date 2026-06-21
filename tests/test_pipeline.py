"""
Behavioural tests for the pipeline's core logic.

Runs with pytest *or* as a plain script (`python tests/test_pipeline.py`), so
it works even where pytest isn't installed.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import ingest, clean, score, pipeline  # noqa: E402


def test_exact_dedup_drops_identical_urls():
    arts = [
        {"title": "Mars to buy Kellanova", "summary": "x", "url": "https://a.com/x?utm_source=feed"},
        {"title": "Mars to buy Kellanova (copy)", "summary": "x", "url": "https://a.com/x"},
    ]
    reps, stats = clean.deduplicate(arts)
    # same URL once tracking params are stripped -> exactly one survivor
    assert stats["after_exact_dedup"] == 1


def test_near_dup_merges_cross_outlet_reports():
    """The 3 Mars/Kellanova reports in the sample must collapse to one cluster."""
    arts, _ = ingest.load_sample()
    reps, stats = clean.deduplicate(arts)
    mars = [r for r in reps if "kellanova" in r["title"].lower()]
    assert len(mars) == 1, "Mars/Kellanova reports should merge into one"
    assert mars[0]["cluster_size"] == 3
    assert len(mars[0]["corroborating_sources"]) == 3


def test_near_dup_does_not_over_merge():
    """Distinct deals that share one common word must NOT merge."""
    arts, _ = ingest.load_sample()
    reps, stats = clean.deduplicate(arts)
    # 30 sample items, 5 true duplicates -> 25 representatives
    assert stats["after_near_dedup"] == 25


def test_relevance_requires_both_signals():
    deal_no_fmcg = {"title": "Software firm acquires security start-up for $1.2bn", "summary": "cybersecurity platform for IT customers"}
    fmcg_no_deal = {"title": "New snack flavour launches nationwide", "summary": "a leading snack brand launched a limited-edition flavour in grocery stores"}
    both = {"title": "PepsiCo to acquire soda brand poppi", "summary": "PepsiCo agreed to acquire beverage brand poppi"}
    assert score.score_relevance(deal_no_fmcg)["is_relevant"] is False
    assert score.score_relevance(fmcg_no_deal)["is_relevant"] is False
    assert score.score_relevance(both)["is_relevant"] is True


def test_raised_guidance_is_not_a_deal_signal():
    earnings = {"title": "Consumer goods giant posts higher sales", "summary": "the company raised its full-year guidance on price increases"}
    assert score.score_relevance(earnings)["is_relevant"] is False


def test_credibility_tiers_and_corroboration():
    wire = score.source_credibility("reuters.com", "Reuters")
    trade = score.source_credibility("fooddive.com", "Food Dive")
    pr = score.source_credibility("prnewswire.com", "PR Newswire")
    assert wire["score"] > trade["score"] > pr["score"]
    assert pr["is_press_release"] is True
    # corroboration lifts credibility above the bare source score
    art = {"source_domain": "fooddive.com", "publisher": "Food Dive",
           "corroborating_sources": ["fooddive.com", "reuters.com", "bloomberg.com"]}
    assert score.score_credibility(art)["credibility"] > trade["score"]


def test_deal_fact_extraction():
    facts = score.extract_deal_facts({
        "title": "Mars to acquire Kellanova in $36 billion deal",
        "summary": "Mars acquires Kellanova for about $36 billion.",
    })
    assert facts["deal_type"] == "Acquisition"
    assert facts["deal_value"] == "$36 billion"


def test_full_pipeline_sample():
    result = pipeline.run_pipeline(use_live=False, use_llm=False)
    s = result.stage_stats
    assert s["ingested"] == 30
    assert s["after_near_dedup"] == 25
    assert s["relevant"] == 21          # 25 deduped − 4 off-topic items
    nl = result.newsletter
    assert nl["counts"]["lead"] >= 1
    assert nl["lead_deals"][0]["title"]          # lead deal has a headline
    assert any("De-duplication" in m for m in nl["methodology"])


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS  {name}")
            except AssertionError as e:
                failed += 1
                print(f"FAIL  {name}: {e}")
    print(f"\n{'ALL TESTS PASSED' if not failed else f'{failed} TEST(S) FAILED'}")
    sys.exit(1 if failed else 0)
