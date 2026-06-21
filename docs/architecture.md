# Architecture & design notes

This document expands on the four-stage pipeline, the data model, and the key
algorithmic choices. For the high-level picture see [`assets/architecture.svg`](../assets/architecture.svg)
and the README.

## Design goals

1. **Minimal, inspectable "agent" flow** - `ingestion -> cleaning -> scoring ->
   newsletter`. Each stage is a pure function over a list of article dicts and
   returns counts, so the whole funnel is observable.
2. **Transparent, rule-based scoring** - no opaque model decides relevance or
   credibility. Every score is reconstructable from fields attached to the
   article (`matched_deal_terms`, `corroborating_sources`, …).
3. **Robust to a restricted host** - the core logic is pure standard library;
   the only network dependency (RSS) degrades gracefully to a bundled dataset.
4. **Optional intelligence, never required** - an LLM improves the prose when a
   key is present; the system is fully functional without it.

## Data model

A single flat `article` dict flows through every stage and accretes fields:

| Stage | Adds |
|---|---|
| ingest | `id, title, summary, url, publisher, source_domain, published, published_dt` |
| clean  | `cluster_size, corroborating_sources, duplicate_urls` (+ internal `_entities`, `_content`) |
| score  | `relevance, is_relevant, matched_deal_terms, matched_fmcg_terms, credibility, credibility_tier, is_press_release, corroboration_count, deal_type, deal_value, acquirer, target, rank_score` |

`pipeline.run_pipeline()` returns a `PipelineResult` carrying the final articles,
the structured newsletter, the per-stage `stage_stats`, and the per-feed
`fetch_log`.

## Stage 2 - de-duplication in depth

Two passes:

1. **Exact** - normalise the URL (lowercase host, strip tracking params and
   fragments) and the title (drop a trailing ` - Publisher`, lowercase, strip
   punctuation). Identical normalised URL or title => drop.

2. **Near-duplicate** - fingerprint each story as
   `(entities, content)` where `entities` = lowercased capitalised tokens +
   numeric figures, and `content` = entities ∪ significant content words.
   Similarity is a blend of two **overlap coefficients**:

   ```
   sim = 0.5 · |Ea ∩ Eb|/min(|Ea|,|Eb|)  +  0.5 · |Ca ∩ Cb|/min(|Ca|,|Cb|)
   ```

   Two reports merge iff they **share ≥ 2 entities** and `sim ≥ 0.50`. The
   "≥ 2 entities" gate is what prevents a single shared common word from forcing
   a false merge - empirically it cleanly separates true cross-outlet duplicates
   (≈ 0.67–0.81 on the sample) from unrelated FMCG-deal pairs (≈ 0.03–0.14).
   **Union-find** turns pairwise links into clusters; the representative is the
   highest-credibility, then most-recent member. Cluster size feeds the
   corroboration signal in scoring.

   *Why overlap coefficient, not Jaccard?* Outlet summaries differ in length
   (a Reuters wire vs. a trade-press write-up). Jaccard penalises length
   differences; the overlap coefficient (`/min`) measures how much of the
   *shorter* fingerprint is contained in the longer - the right question for
   "is this the same story?".

## Stage 3 - relevance gating

Relevance is intentionally a **conjunction**: `deal_signal > 0 AND fmcg_signal > 0`.
This is what filters out the two common false positives:

- An **FMCG story with no deal** (a product launch, an earnings beat) - has an
  FMCG signal but no deal signal -> capped, dropped.
- A **deal in another industry** (an enterprise-software acquisition) - has a
  deal signal but no FMCG signal -> capped, dropped.

Title matches are weighted ×2 because headlines are the strongest cue. Ambiguous
weak terms are handled deliberately: bare `raises/raised` is excluded from the
deal vocabulary (it false-fires on "raised guidance"), while genuine funding is
still caught by `funding round`, `series a/b/c`, `investment`, etc.

## Stage 3 - credibility & corroboration

`credibility = base_source_tier + corroboration_bonus − lone_press_release_penalty`,
clamped to `[0, 100]`. The corroboration bonus (`+4` per extra independent
outlet, capped `+12`) encodes a simple, defensible idea: a deal reported by
Reuters *and* Bloomberg *and* a trade outlet is more trustworthy than the same
deal from a single unknown source. Press-release wires are flagged
(`is_press_release`) and a lone release loses trust.

## Extensibility

Everything tunable lives in `src/config.py`:

- `GOOGLE_NEWS_QUERIES`, `DIRECT_FEEDS` - what to ingest.
- `DEAL_KEYWORDS`, `FMCG_CATEGORY_KEYWORDS`, `FMCG_COMPANY_KEYWORDS` - the
  relevance vocabulary and weights.
- `CREDIBILITY_TIERS` - the source allow-list and scores.
- `THRESHOLDS`, `RANK_WEIGHTS` - dedup similarity, relevance floor, look-back,
  ranking blend.

Adding a region or category is a config edit, not a code change.
