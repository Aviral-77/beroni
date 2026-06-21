#!/usr/bin/env python3
# Run the whole pipeline from the command line and write all the output files.
#
# Usage:
# python scripts/run_pipeline.py [--no-llm] [--days N] [--min-relevance N] [--out DIR]

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import pipeline, exporters, newsletter  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="FMCG deal-intelligence newsletter pipeline")
    ap.add_argument("--no-llm", action="store_true", help="skip LLM summaries (template only)")
    ap.add_argument("--days", type=int, default=14, help="lookback window in days")
    ap.add_argument("--min-relevance", type=int, default=35, help="minimum relevance score (0-100)")
    ap.add_argument("--out", default="data/outputs", help="output directory")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)

    print("Running pipeline: ingest, clean, score, newsletter...")
    result = pipeline.run_pipeline(
        lookback_days=args.days,
        min_relevance=args.min_relevance,
        use_llm=not args.no_llm,
    )

    s = result.stage_stats
    ok_feeds = sum(1 for f in result.fetch_log if f["status"] == "ok")
    if ok_feeds == 0:
        print("\nWARNING: No RSS feeds were reachable. Check your internet connection.")

    print(f"\nSource: LIVE ({ok_feeds} feed(s) reached)")
    print("Funnel:")
    print(f"  ingested            : {s.get('ingested')}")
    print(f"  after exact dedup   : {s.get('after_exact_dedup')}")
    print(f"  after near-dup merge: {s.get('after_near_dedup')}  "
          f"({s.get('duplicates_removed')} duplicates merged)")
    print(f"  relevant (kept)     : {s.get('relevant')}")
    print(f"  filtered out        : {s.get('filtered_out')}")
    print(f"  LLM summaries       : {'yes' if result.newsletter['llm_used'] else 'no (template)'}")

    files = exporters.export_all(result.newsletter, result.articles)
    md = newsletter.to_markdown(result.newsletter)
    files["fmcg_newsletter.md"] = md.encode("utf-8")

    print("\nWriting outputs to", args.out)
    for name, data in files.items():
        path = os.path.join(args.out, name)
        with open(path, "wb") as fh:
            fh.write(data)
        print(f"  {path}  ({len(data):,} bytes)")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
