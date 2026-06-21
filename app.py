"""
FMCG Deal Intelligence — Streamlit demo app.

A one-screen showcase of the agent pipeline:
    ingest → clean (de-dup) → score (relevance + credibility) → newsletter

Run locally:   streamlit run app.py
Deploy:        push to GitHub → share.streamlit.io → point at app.py
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src import pipeline, exporters, newsletter
from src import config

st.set_page_config(
    page_title="FMCG Deal Intelligence",
    page_icon="📰",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.title("📰 FMCG Deal Intelligence")
st.caption(
    "Real-time M&A & investment newsletter for fast-moving consumer goods — "
    "an ingestion → de-duplication → scoring → newsletter agent pipeline."
)

# ---------------------------------------------------------------------------
# Sidebar controls
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Controls")
    data_mode = st.radio(
        "Data source",
        ["Live news feeds", "Bundled sample"],
        help="Live mode pulls public RSS feeds in real time. If the host blocks "
             "outbound news access, the app automatically falls back to a bundled "
             "illustrative dataset so the demo still runs.",
    )
    lookback = st.slider("Look-back window (days)", 3, 30, config.THRESHOLDS["lookback_days"])
    min_rel = st.slider("Minimum relevance score", 0, 100, config.THRESHOLDS["min_relevance"], step=5)
    use_llm = st.toggle(
        "Use Claude for summaries",
        value=True,
        help="If an ANTHROPIC_API_KEY is configured, Claude writes the analyst "
             "summaries. Otherwise the app uses transparent template summaries.",
    )
    run = st.button("🚀 Run pipeline", type="primary", use_container_width=True)
    st.markdown("---")
    st.markdown(
        "**Pipeline stages**\n\n"
        "1. **Ingest** — public RSS/Atom feeds\n"
        "2. **Clean** — exact + near-dup merge\n"
        "3. **Score** — relevance + credibility\n"
        "4. **Newsletter** — ranked, structured draft"
    )


@st.cache_data(show_spinner=False, ttl=900)
def _run(use_live: bool, lookback: int, min_rel: int, use_llm: bool):
    """Cached pipeline run (15 min) keyed on the control values."""
    result = pipeline.run_pipeline(
        use_live=use_live, lookback_days=lookback,
        min_relevance=min_rel, use_llm=use_llm,
    )
    md = newsletter.to_markdown(result.newsletter)
    files = exporters.export_all(result.newsletter, result.articles)
    return result, md, files


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if run or "result" not in st.session_state:
    with st.spinner("Running pipeline: ingest → clean → score → newsletter…"):
        result, md, files = _run(
            use_live=(data_mode == "Live news feeds"),
            lookback=lookback, min_rel=min_rel, use_llm=use_llm,
        )
    st.session_state.update(result=result, md=md, files=files)

result = st.session_state["result"]
md = st.session_state["md"]
files = st.session_state["files"]
nl = result.newsletter
s = result.stage_stats

# ---- data-source banner ----------------------------------------------------
if result.source == "sample":
    st.info(
        "📦 **Using the bundled sample dataset.** Either sample mode is selected, "
        "or live news access is blocked on this host. The full pipeline still runs; "
        "deploy with open internet to ingest real-time feeds.",
        icon="ℹ️",
    )
else:
    ok = sum(1 for f in result.fetch_log if f["status"] == "ok")
    st.success(f"🟢 Live mode — pulled from {ok} feed(s) in real time.", icon="✅")

# ---- funnel metrics --------------------------------------------------------
st.subheader("Pipeline funnel")
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Ingested", s.get("ingested", 0))
c2.metric("After dedup", s.get("after_near_dedup", 0),
          delta=f"-{s.get('duplicates_removed', 0)} dupes", delta_color="off")
c3.metric("Relevant", s.get("relevant", 0),
          delta=f"-{s.get('filtered_out', 0)} filtered", delta_color="off")
c4.metric("Lead deals", nl["counts"]["lead"])
c5.metric("Summaries", "Claude" if nl["llm_used"] else "Template")

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_news, tab_data, tab_logic, tab_dl = st.tabs(
    ["📰 Newsletter", "🔢 Raw data", "🧠 Pipeline logic", "⬇️ Downloads"]
)

with tab_news:
    st.markdown(md, unsafe_allow_html=True)

with tab_data:
    st.caption(
        "Every de-duplicated article with its scores. `relevance` and `credibility` "
        "are 0–100; `is_relevant` items below the threshold are excluded from the draft."
    )
    cols = [
        "rank_score", "relevance", "credibility", "is_relevant", "deal_type",
        "deal_value", "title", "publisher", "credibility_tier",
        "corroboration_count", "cluster_size", "published", "url",
    ]
    df = pd.DataFrame(result.articles)
    df = df[[c for c in cols if c in df.columns]]
    st.dataframe(df, use_container_width=True, height=460)

with tab_logic:
    st.markdown("#### How each stage works")
    st.markdown(
        "- **Ingestion** — public RSS/Atom feeds: Google News deal-query feeds "
        "(which attribute each item to its original publisher) plus FMCG trade "
        "press. No paywalled or private sources.\n"
        f"- **De-duplication** — exact match on normalised URL/title, then "
        f"near-duplicate clustering: each story is *fingerprinted* by its named "
        f"entities (companies, brands) and figures plus significant content words. "
        f"Two reports merge when they share **≥2 entities** and their blended "
        f"overlap (entity + content overlap coefficients) reaches "
        f"**{config.THRESHOLDS['near_dup_similarity']:.2f}**. The most credible / "
        f"recent report is kept; the rest become corroboration.\n"
        "- **Relevance** — an item must show **both** a deal signal "
        "(acquire / merger / stake / funding…) **and** an FMCG signal (category or "
        "named consumer-goods company). Title matches count double. Items below the "
        "relevance threshold are dropped.\n"
        "- **Credibility** — a transparent source-tier allow-list (global wire > "
        "trade press > general > press-release wires), **plus** a corroboration "
        "bonus when multiple independent outlets report the same deal, **minus** a "
        "penalty for lone press releases. We rate the *source*, not each claim.\n"
        "- **Ranking** — composite of relevance (45%), credibility (30%), "
        "recency (15%) and corroboration (10%)."
    )
    st.markdown("#### This run's assumptions")
    for line in nl["methodology"]:
        st.markdown(f"- {line}")

    with st.expander("Per-feed fetch log"):
        st.dataframe(pd.DataFrame(result.fetch_log), use_container_width=True)

with tab_dl:
    st.caption("Download the raw data and the structured newsletter in every format.")
    mimes = {
        "csv": "text/csv",
        "json": "application/json",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
    labels = {
        "csv": "⬇️ Raw data (CSV)", "json": "⬇️ Raw data (JSON)",
        "xlsx": "⬇️ Newsletter (Excel)", "docx": "⬇️ Newsletter (Word)",
        "pptx": "⬇️ Newsletter (PowerPoint)",
    }
    cols = st.columns(len(files))
    for col, (name, data) in zip(cols, files.items()):
        ext = name.rsplit(".", 1)[-1]
        col.download_button(
            labels.get(ext, name), data=data, file_name=name,
            mime=mimes.get(ext, "application/octet-stream"),
            use_container_width=True,
        )
    st.markdown("Also available: the markdown preview shown in the **Newsletter** tab.")
    st.download_button(
        "⬇️ Newsletter (Markdown)", data=md.encode("utf-8"),
        file_name="fmcg_newsletter.md", mime="text/markdown",
    )

st.markdown("---")
st.caption(
    f"Generated {nl['generated_at'][:19]}Z · "
    f"{'Claude-written' if nl['llm_used'] else 'template'} summaries · "
    "Decision-support only, not investment advice."
)
