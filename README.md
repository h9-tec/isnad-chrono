# isnad-chrono

Scores every teacher-to-student link in the hadith chains (isnads) of hdith.com's corpus by the probability that the two narrators could have met, using narrator death and birth years with uncertainty, combined with textual sama' (audition) evidence. The scores are evaluated against classical critics' denials of contact (al-Marasil, Tuhfat al-Tahsil). The method is per-edge, explainable and uses no training.

## Setup

```
uv sync
mkdir -p ~/.config/isnad-chrono
echo 'FIRECRAWL_API_KEY=<your key>' > ~/.config/isnad-chrono/.env
```

The key is only needed for the Firecrawl fetcher. Python >= 3.12.

## Pipeline

Run in this order. All commands are `uv run python -m isnad.cli <command>`.

```
fetch rawis                                  # enumerate narrator URLs from the sitemap
fetch books [--book b-2]                     # enumerate hadith URLs per book
fetch run --kind rawi   --fetcher firecrawl  # fetch narrator pages (raw HTML cached)
fetch run --kind hadith --fetcher firecrawl --book b-1   # Stage 2: one book at a time, b-1 ... b-6
fetch run --kind hadith --fetcher local                  # or the local crawler (<= 3 req/s)
fetch status [--kind K] [--book B]           # queue counts
fetch jobs                                   # Firecrawl job ledger (id, kind, n, status, first/last URL)
fetch recover --job <id> [--kind K]          # persist the results of an already-paid job
build                                        # parse cache -> data/*.parquet
gold                                         # gold negatives/positives from marasil + tuhfa
score --denials data/denials.parquet         # p_meet, sama evidence, verdicts
validate                                     # data/metrics.json, figures/
report                                       # weak_edges.csv, date_errors.csv
export --data-dir data --out release         # release/ for the dataset
```

Stage 2 (the Six Books) must run per book: `fetch run --kind hadith --fetcher firecrawl --book b-1`, then `b-2` ... `b-6`. Without `--book` or `--limit`, a Firecrawl hadith run refuses to start (prints the pending count, exits 2), so a single command cannot spend credits on all 245 books.

Every submitted Firecrawl job is printed (job id, count, first/last URL) and stored in the `jobs` table of `data/queue.sqlite` before polling. If a run dies after paying for a job, `fetch jobs` lists it and `fetch recover --job <id>` persists its results. A POST that times out may still have created a job; it is logged with the batch's first/last URL.

### v2 pipeline (isnad-cum-matn, Hugging Face release)

Run after `build`, in this order (`uv run python -m isnad.cli <command>`, default paths under `data/`):

```
chains                           # chains.parquet: one chain per path to the compiler (ح/و/وقال splits, joins)
groups                           # groups, occurrences, segments (hashes), shawahid; text only in data/text/
dating                           # rawi_dates_inferred.parquet: narrator intervals by constraint propagation
tree                             # tree_nodes, report_dates (common links, dates), shawahid_companions
edits                            # edits.parquet + edit_rates.parquet: wording-change attribution
export-hf --out release_hf [--push]   # release_hf/: configs, checks.json, README from DATASET_CARD_v2.md
```

`--push` reads `HF_TOKEN` from `~/.config/isnad-chrono/.env` and uploads `release_hf/` to the HF dataset repo.

## Data layout

- `data/raw/html/{hadith,rawi}/` raw page cache (gitignored, never re-fetched)
- `data/queue.sqlite` fetch queue
- `data/*.parquet`, `data/metrics.json`, `data/*.csv` pipeline outputs (gitignored)
- `gold/` hand-prepared gold inputs
- `release/` v1 export for publication (gitignored): `edges`, `edge_scores`, `rawi_dates`, `MANIFEST.json`
- `release_hf/` v2 Hugging Face release built by `export-hf` (gitignored): `data/<config>.parquet`, `checks.json`, `MANIFEST.json`, `README.md`
- `DATASET_CARD_v2.md` template of the HF dataset card (`{{placeholders}}` filled from the checks by `export-hf`)
- `paper/` outline

## Licensing

Code: MIT (see `LICENSE`). The released dataset is licensed CC-BY-4.0 and contains derived numbers only (IDs, years, flags, scores, verdicts). No hdith.com text, names, or matn is redistributed; the export enforces a column denylist. hdith.com is the data source and is cited. v0.1 is published on Hugging Face (https://huggingface.co/datasets/HeshamHaroon/isnad-chrono) as derived numbers and text hashes only. The license of hdith.com itself is unstated; no source text is redistributed. Takedown or correction requests: the discussions of the HF dataset repo.

## Contact

h9-tec (GitHub).
