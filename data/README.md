# data/

This directory stores all **datasets and data artefacts** used by AetheerAI.

```
data/
├── raw/         Original, immutable data as received from sources
├── processed/   Cleaned, transformed, or feature-engineered data
└── exports/     Final outputs emitted by agents (reports, CSVs, JSON results)
```

## Conventions

| Sub-directory | What goes here                                              | tracked in git? |
|---------------|-------------------------------------------------------------|-----------------|
| `raw/`        | Source CSVs, JSON dumps, scraped HTML (don't modify these)  | Small sets only |
| `processed/`  | Normalised/tokenised data, embeddings, parquet files        | No              |
| `exports/`    | Agent-generated outputs (per run, timestamped)              | No              |

## Large file policy

- Files > 10 MB should NOT be committed. Use `.gitignore` or Git LFS.
- Document data sources in `data/raw/SOURCES.md`.
