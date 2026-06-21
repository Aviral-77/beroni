# src/

The actual pipeline code. Each file is one step, and they run in this order:
ingest, clean, score, newsletter.

| File | What it does |
|------|--------------|
| `config.py` | All the settings in one place: the list of news feeds, the deal and FMCG keyword lists, the source credibility tiers, and the numeric thresholds. If you want to tune the system, you edit this file and nothing else. |
| `ingest.py` | Step 1. Downloads the RSS/Atom feeds, parses the XML, and turns each news item into a plain dict. Also loads the bundled sample data when the feeds can't be reached. |
| `clean.py` | Step 2. Removes duplicates. First drops exact repeats (same URL or title), then merges stories that are the same deal reported by different outlets. |
| `score.py` | Step 3. Scores each story for relevance (is it really an FMCG deal?) and credibility (how trustworthy is the source?), pulls out deal facts like value and parties, and ranks everything. |
| `newsletter.py` | Step 4. Takes the ranked stories and builds the newsletter: lead deals, a short "also in the news" list, summaries, and a methodology note. Can use an LLM for the summaries if a key is set, otherwise uses a template. |
| `pipeline.py` | Glues the four steps together and returns one result object. This is what the app and the CLI call. |
| `exporters.py` | Writes the result out to CSV, JSON, Excel, Word, and PowerPoint. |
| `__init__.py` | Marks the folder as a Python package. Empty. |
