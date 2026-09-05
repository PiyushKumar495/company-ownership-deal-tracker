# Company Ownership & Deal Data Tracker

A small end-to-end pipeline that ingests private-market deal and ownership data
from multiple (often conflicting) sources, uses an LLM to extract structured
fields from unstructured press-release text, reconciles conflicting records,
and produces an evidence-backed, validated dataset.

This project was built to demonstrate the core workflow behind private-markets
research and data-quality roles: interpreting deal/ownership data from
structured and unstructured sources, applying judgment under ambiguity, using
AI-assisted tools to speed up research, and maintaining an audit trail of how
conflicts were resolved.

## Why this project exists

Real deal data is messy: a company's own press release, a news outlet, and a
data aggregator will often report the *same* funding round with different
valuations, dates, or investor lists. A useful research/data pipeline can't
just pick the newest or the biggest number — it has to track every source,
apply a consistent trust hierarchy, flag anything that can't be resolved
automatically, and leave a paper trail for a human reviewer.

That's what this pipeline does, end to end, using synthetic sample data.

## Architecture

```
data/raw/                    Unstructured + semi-structured input
  ├─ press_release_source_a.json   (company self-reported, unstructured text)
  ├─ press_release_source_b.json   (news aggregator, unstructured text)
  └─ filings_source_c.csv          (structured "regulatory filing"-style data)
        │
        ▼
src/ai_extract.py            Uses an LLM (Claude) to pull structured fields
                              (company, investors, round, amount, valuation,
                              date) out of unstructured press-release text.
                              Falls back to a rule-based extractor if no API
                              key is configured, so the pipeline always runs.
        │
        ▼
src/ingest.py                Normalizes every source into a common schema and
                              loads it into SQLite, tagging each row with its
                              source and a trust tier.
        │
        ▼
src/reconcile.py             Compares records for the same company/round
                              across sources. Flags conflicts (valuation/date/
                              ownership mismatches), auto-resolves using a
                              trust hierarchy where the gap is small, and
                              marks anything else "needs_review".
        │
        ▼
src/export_report.py         Writes a validated dataset + a human-readable
                              conflict/resolution report (Markdown + CSV) —
                              the "evidence-backed documentation" artifact.
```

Run the whole thing with:

```bash
python -m src.pipeline
```

Output lands in `output/`:
- `validated_deals.csv` — the cleaned, reconciled dataset
- `reconciliation_report.md` — every conflict found and how it was resolved
- `deal_tracker.db` — the SQLite database with full source-level history

## Data model

| Table | Purpose |
|---|---|
| `companies` | Canonical company records |
| `investors` | Canonical investor records |
| `funding_rounds` | One row per (source, company, round) — deliberately **not** deduplicated on ingest, so every source's claim is preserved |
| `ownership` | Investor → company stakes, per source |
| `data_conflicts` | Every detected mismatch, its resolution status, and the reasoning |

Keeping every source's version of a fact (rather than overwriting on ingest)
is what makes the reconciliation step possible and auditable.

## AI-assisted extraction

`src/ai_extract.py` sends raw press-release text to Claude with a prompt that
asks for strict JSON output (company, investors, round type, amount,
valuation, date). This mirrors the "AI-enabled research & productivity"
part of the workflow — using an LLM to speed up pulling structured facts out
of free-text announcements instead of manually re-reading every release.

To use real AI extraction:

```bash
cp .env.example .env
# edit .env and set ANTHROPIC_API_KEY=sk-ant-...
pip install -r requirements.txt
python -m src.pipeline
```

Without an API key, the pipeline automatically falls back to a lightweight
regex-based extractor (`_fallback_extract` in `src/ai_extract.py`) so the
project still runs end-to-end for anyone reviewing the code on GitHub.

## Reconciliation logic (the core "judgment under ambiguity" piece)

For each company + round, `src/reconcile.py`:

1. Groups all source records for that round together.
2. Compares valuation and amount figures — if they differ by more than a
   configurable threshold (default 8%), the round is flagged as a conflict.
3. Applies a trust hierarchy (`company_filing` > `press_release` >
   `news_aggregator` > `ai_extracted`) to propose a resolved value.
4. If the gap is small (<8%) or only one source exists, it auto-resolves.
   If sources disagree materially, it's marked `needs_review` — the pipeline
   never silently guesses on a large discrepancy.
5. Separately checks that summed ownership stakes per company don't exceed
   100% (a common data-quality bug when sources overlap), flagging any that
   do.

Every decision — resolved or not — is written to `data_conflicts` with a
plain-English `resolution_note`, so a reviewer can see *why*.

## Sample output

Running the pipeline on the included sample data produces a handful of
deliberately-planted conflicts (e.g., two sources reporting different
valuations for the same Series B round, and one company with slightly
over-100% summed ownership) so you can see the reconciliation logic work.
See `output/reconciliation_report.md` after running it.

## Tech stack

- Python 3.10+
- SQLite (via stdlib `sqlite3`) — no external DB server needed to run this
- `pandas` for tabular cleanup/export
- Anthropic API (Claude) for unstructured-text extraction, with a
  dependency-free fallback
- `pytest` for the reconciliation-logic tests

## Possible extensions

- Swap the sample CSV/JSON sources for a real feed (e.g. SEC EDGAR full-text
  search API, or a scraped press-release RSS feed)
- Add a second trust-hierarchy dimension (source recency, not just source
  type)
- Move from SQLite to Postgres and add a small Streamlit view over
  `data_conflicts` for a reviewer queue
