# data/

Holds the sample input and the generated output files.

| File / folder | What it is |
|---------------|-----------|
| `sample_articles.json` | A small fixed set of 30 news items used when the live feeds aren't available (for example on a host with no internet). It includes a few duplicate reports of the same deal and a few off-topic items on purpose, so the dedup and relevance steps have something to act on. |
| `outputs/` | The generated deliverables. Created when you run the pipeline. |

## outputs/

| File | What it is |
|------|-----------|
| `fmcg_deals_raw_*.csv` | Every deduplicated article with its scores, as a spreadsheet-friendly table. |
| `fmcg_deals_raw_*.json` | The same raw data as JSON. |
| `fmcg_newsletter_*.xlsx` | The newsletter as an Excel workbook (newsletter, raw data, and methodology on separate sheets). |
| `fmcg_newsletter_*.docx` | The newsletter as a Word document. |
| `fmcg_newsletter_*.pptx` | The newsletter as a slide deck. |
| `fmcg_newsletter.md` | The newsletter as plain markdown. |
