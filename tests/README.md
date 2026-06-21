# tests/

| File | What it does |
|------|--------------|
| `test_pipeline.py` | Checks the core logic: exact dedup, near-duplicate merging (and that it doesn't over-merge), the relevance two-signal gate, the "raised guidance" edge case, credibility tiers, deal-fact extraction, and a full run over the sample data. |

Run them with either:

```bash
pytest
# or, if you don't have pytest installed:
python tests/test_pipeline.py
```
