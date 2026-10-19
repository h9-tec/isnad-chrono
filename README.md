# isnad-chrono

Scores every teacher-to-student link in the hadith chains (isnads) of hdith.com's corpus by the probability that the two narrators could have met, using narrator death and birth years with uncertainty, combined with textual sama' (audition) evidence. The scores are validated against classical critics' denials of contact (al-Marasil, Tuhfat al-Tahsil). The method is per-edge, explainable and uses no training.

## Setup

```
uv sync
mkdir -p ~/.config/isnad-chrono
echo 'FIRECRAWL_API_KEY=<your key>' > ~/.config/isnad-chrono/.env
```

The key is only needed for the Firecrawl fetcher. Python 3.12.

## Pipeline

Run in this order. All commands are `uv run python -m isnad.cli <command>`.

```
fetch rawis                                  # enumerate narrator URLs from the sitemap
fetch books [--book b-2]                     # enumerate hadith URLs per book
fetch run --kind rawi   --fetcher firecrawl  # fetch narrator pages (raw HTML cached)
fetch run --kind hadith --fetcher firecrawl  # or --fetcher local (<= 3 req/s)
fetch status [--kind K] [--book B]           # queue counts
build                                        # parse cache -> data/*.parquet
gold                                         # gold negatives/positives from marasil + tuhfa
score --denials data/denials.parquet         # p_meet, sama evidence, verdicts
validate                                     # data/metrics.json, figures/
report                                       # weak_edges.csv, date_errors.csv
export --data-dir data --out release         # release/ for the dataset
```

## Data layout

- `data/raw/html/{hadith,rawi}/` raw page cache (gitignored, never re-fetched)
- `data/queue.sqlite` fetch queue
- `data/*.parquet`, `data/metrics.json`, `data/*.csv` pipeline outputs (gitignored)
- `gold/` hand-prepared gold inputs
- `release/` export for publication (gitignored): `edges`, `edge_scores`, `rawi_dates`, `MANIFEST.json`
- `paper/` outline

## Licensing

Code: MIT. The released dataset contains derived numbers only (IDs, years, flags, scores, verdicts). No hdith.com text, names, or matn is redistributed; the export enforces a column denylist. hdith.com is the data source and is cited. Its license is unstated, so the site owners are to be contacted before the dataset is published.

## Contact

h9-tec (GitHub).
