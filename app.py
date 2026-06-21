import pandas as pd
import streamlit as st

from src import pipeline, exporters, newsletter, config

st.set_page_config(page_title="FMCG Deal Intelligence", layout="wide")

st.title("FMCG Deal Intelligence")
st.caption("Real-time M&A and investment newsletter for fast-moving consumer goods.")

with st.sidebar:
    st.header("Controls")
    lookback = st.slider("Look-back window (days)", 3, 30, config.THRESHOLDS["lookback_days"])
    min_rel = st.slider("Minimum relevance score", 0, 100, config.THRESHOLDS["min_relevance"], step=5)
    use_llm = st.toggle("Use LLM for summaries", value=True)
    run = st.button("Run pipeline", type="primary", use_container_width=True)
    st.markdown("---")
    st.markdown(
        "**Stages**\n\n"
        "1. Ingest - public RSS/Atom feeds\n"
        "2. Clean - exact + near-dup merge\n"
        "3. Score - relevance + credibility\n"
        "4. Newsletter - ranked, structured draft"
    )


@st.cache_data(show_spinner=False, ttl=900)
def _run(lookback, min_rel, use_llm):
    result = pipeline.run_pipeline(
        lookback_days=lookback,
        min_relevance=min_rel,
        use_llm=use_llm,
    )
    md = newsletter.to_markdown(result.newsletter)
    files = exporters.export_all(result.newsletter, result.articles)
    return result, md, files


if run or "result" not in st.session_state:
    with st.spinner("Fetching live feeds and running pipeline..."):
        result, md, files = _run(lookback=lookback, min_rel=min_rel, use_llm=use_llm)
    st.session_state.update(result=result, md=md, files=files)

result = st.session_state["result"]
md = st.session_state["md"]
files = st.session_state["files"]
nl = result.newsletter
s = result.stage_stats

ok_feeds = sum(1 for f in result.fetch_log if f["status"] == "ok")
if ok_feeds == 0:
    st.error(
        "Could not reach any RSS feeds. Check your internet connection and try again. "
        "If the problem persists, some feeds may be temporarily unavailable."
    )
else:
    st.success(f"Live mode - pulled from {ok_feeds} feed(s).")

st.subheader("Pipeline funnel")
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Ingested", s.get("ingested", 0))
c2.metric("After dedup", s.get("after_near_dedup", 0),
          delta=f"-{s.get('duplicates_removed', 0)} dupes", delta_color="off")
c3.metric("Relevant", s.get("relevant", 0),
          delta=f"-{s.get('filtered_out', 0)} filtered", delta_color="off")
c4.metric("Lead deals", nl["counts"]["lead"])
c5.metric("Summaries", "LLM" if nl["llm_used"] else "Template")

tab_news, tab_data, tab_logic, tab_dl = st.tabs(
    ["Newsletter", "Raw data", "Pipeline logic", "Downloads"]
)

with tab_news:
    if not nl["lead_deals"]:
        st.warning(
            "No relevant FMCG deals found. Try lowering the minimum relevance score "
            "or increasing the look-back window."
        )
    else:
        st.markdown(md, unsafe_allow_html=True)

with tab_data:
    cols = [
        "rank_score", "relevance", "credibility", "is_relevant", "deal_type",
        "deal_value", "title", "publisher", "credibility_tier",
        "corroboration_count", "cluster_size", "published", "url",
    ]
    df = pd.DataFrame(result.articles)
    if not df.empty:
        df = df[[c for c in cols if c in df.columns]]
        st.dataframe(df, use_container_width=True, height=460)
    else:
        st.info("No articles to display.")

with tab_logic:
    st.markdown("#### How each stage works")
    st.markdown(
        "- **Ingestion** - public RSS/Atom only (Google News + trade press). No paywalls.\n"
        f"- **De-duplication** - exact URL/title match, then near-dup clustering. Stories are "
        f"fingerprinted by named entities and figures; two reports merge when they share at least "
        f"2 entities and their blended overlap reaches **{config.THRESHOLDS['near_dup_similarity']}**.\n"
        "- **Relevance** - must have both a deal signal and an FMCG signal (title counts double). "
        "Items below the threshold are dropped.\n"
        "- **Credibility** - source-tier allow-list plus a corroboration bonus, minus a lone "
        "press-release penalty.\n"
        "- **Ranking** - relevance 45%, credibility 30%, recency 15%, corroboration 10%."
    )
    st.markdown("#### This run")
    for line in nl["methodology"]:
        st.markdown(f"- {line}")
    with st.expander("Per-feed fetch log"):
        st.dataframe(pd.DataFrame(result.fetch_log), use_container_width=True)

with tab_dl:
    if result.articles:
        mimes = {
            "csv": "text/csv",
            "json": "application/json",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        }
        labels = {
            "csv": "Raw data (CSV)", "json": "Raw data (JSON)",
            "xlsx": "Newsletter (Excel)", "docx": "Newsletter (Word)",
            "pptx": "Newsletter (PowerPoint)",
        }
        dl_cols = st.columns(len(files))
        for col, (name, data) in zip(dl_cols, files.items()):
            ext = name.rsplit(".", 1)[-1]
            col.download_button(
                labels.get(ext, name), data=data, file_name=name,
                mime=mimes.get(ext, "application/octet-stream"),
                use_container_width=True,
            )
        st.download_button(
            "Newsletter (Markdown)", data=md.encode("utf-8"),
            file_name="fmcg_newsletter.md", mime="text/markdown",
        )
    else:
        st.info("No data to download. Run the pipeline with live feeds first.")

st.markdown("---")
st.caption(
    f"Generated {nl['generated_at'][:19]}Z. "
    f"{'LLM-written' if nl['llm_used'] else 'template'} summaries. "
    "Decision-support only, not investment advice."
)
