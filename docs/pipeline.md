# How the pipeline works

This is a short tour of the project: the steps, why they're set up this way,
what each Python file does, and how to run it.

## The idea

We want a short newsletter of recent FMCG (fast-moving consumer goods) deals,
built automatically from public news. The work splits into four steps that run
one after another:

```
ingest  ->  clean  ->  score  ->  newsletter
```

Each step takes a list of articles and hands a (smaller, cleaner) list to the
next one. Keeping them separate means you can look at the output of any step and
see exactly what happened, which makes the whole thing easy to debug and explain.

## The four steps

### 1. Ingest

Pull news from public RSS feeds: Google News searches for deal queries (like
"FMCG acquisition") plus a few trade-press feeds (Food Dive, Just Food, and so
on). Google News is handy because it tells us the original publisher of each
story, which we use later for credibility.

We parse the feeds with Python's built-in XML parser instead of an outside
library, so there's nothing extra to install or compile. If the feeds can't be
reached, we fall back to a bundled sample file so the app always shows something.

### 2. Clean (remove duplicates)

The same deal gets reported by lots of outlets, so we want each deal once.

- First we drop exact repeats: same URL (after stripping tracking junk) or same
  title.
- Then we catch near-duplicates. Different outlets reword headlines, but they
  all mention the same company names and dollar figures. So we "fingerprint"
  each story by the names and numbers in it, and merge two stories when they
  share at least two of those and look similar enough. We keep the most credible
  copy and remember how many outlets covered it.

Why this way: comparing headline text directly doesn't work, because
"Mars to buy Kellanova" and "Kellanova agrees Mars takeover" barely overlap as
text. The company names and the deal value are what stay the same, so that's
what we match on.

### 3. Score

Two scores per story, both based on simple rules so you can always see why a
story got the number it did.

- Relevance: a story has to look like a deal AND be about FMCG. If it's a deal
  in some other industry, or an FMCG story that isn't a deal, it gets dropped.
- Credibility: based on the source. Big wires score highest, then trade press,
  then general news, then press-release wires. If several independent outlets
  reported the same deal, it gets a small bonus.

We also pull out a few facts with simple pattern matching (deal value, type,
who's buying whom) and rank everything by a weighted mix of the scores plus
recency.

### 4. Newsletter

Take the ranked stories, put the top ones as "lead deals" and the rest as a
short "also in the news" list, write a summary for each, and add a methodology
note so the reader knows how it was made. Summaries can come from an LLM if a
key is set; otherwise we use a plain template, so it works with no setup.

## What each file does

| File | Job |
|------|-----|
| `src/config.py` | All the settings: feeds, keywords, credibility tiers, thresholds. |
| `src/ingest.py` | Step 1. Download and parse the feeds into article dicts. |
| `src/clean.py` | Step 2. Drop exact dupes, then merge near-duplicate deals. |
| `src/score.py` | Step 3. Score relevance and credibility, extract facts, rank. |
| `src/newsletter.py` | Step 4. Build the newsletter and write the summaries. |
| `src/exporters.py` | Save the result as CSV, JSON, Excel, Word, and PowerPoint. |
| `src/pipeline.py` | Run the four steps in order and return one result. |
| `app.py` | The Streamlit demo app. |
| `scripts/run_pipeline.py` | Command-line runner that writes all the output files. |
| `tests/test_pipeline.py` | Tests for the core logic. |

## How to run it

Install the requirements first:

```bash
pip install -r requirements.txt
```

Then either open the app:

```bash
streamlit run app.py
```

or generate the files from the command line:

Outputs in `data/outputs/`.

LLM summaries are optional. To turn them on, set `LLM_API_KEY` and
`FMCG_LLM_MODEL`. Without them the app uses template summaries and works the same
way otherwise.
