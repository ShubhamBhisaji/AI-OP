# data/raw/SOURCES.md
Document every dataset here: where it came from, when it was retrieved, and its licence.

| File | Source | Retrieved | Licence | Notes |
|------|--------|-----------|---------|-------|
| `agent_runs.csv` | Generated — AetheerAI internal telemetry seed | 2026-03-17 | MIT (project) | 40-row representative sample of agent run metrics: latency, cost, tokens, success rate per provider/agent/task |

---

## Adding a new dataset

1. Drop the file into `data/raw/` (do **not** modify it here).
2. Add a row to the table above.
3. Run the pipeline to produce a clean copy in `data/processed/`:
   ```bash
   python main.py --pipeline --input data/raw/<your_file>.csv
   ```
4. Large files (> 10 MB) must be added to `.gitignore` or tracked with Git LFS.
