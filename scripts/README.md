# scripts/

| File | What it does |
|------|--------------|
| `run_pipeline.py` | Command-line runner. Runs the whole pipeline and writes all the output files to `data/outputs/`. Useful when you just want the files without opening the app. |

Examples:

```bash
python scripts/run_pipeline.py                          # live feeds, falls back to sample
python scripts/run_pipeline.py --sample                 # force the bundled sample
python scripts/run_pipeline.py --no-llm --days 7 --min-relevance 40
```
