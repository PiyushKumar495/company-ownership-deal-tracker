-- Company Ownership & Deal Data Tracker schema
-- Note: funding_rounds and ownership are intentionally NOT deduplicated on
-- ingest. Every source's claim is kept as its own row so reconciliation can
-- compare them later. Deduplication/resolution happens in reconcile.py and
-- is recorded in data_conflicts.

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS investors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS funding_rounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    round_type TEXT,
    round_date TEXT,
    amount_usd REAL,
    valuation_usd REAL,
    source TEXT NOT NULL,          -- e.g. company_filing, news_aggregator, ai_extracted
    trust_tier INTEGER NOT NULL,   -- 1 = most trusted, higher = less trusted
    raw_reference TEXT             -- short pointer back to the raw record this came from
);

CREATE TABLE IF NOT EXISTS ownership (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    investor_id INTEGER NOT NULL REFERENCES investors(id),
    round_id INTEGER REFERENCES funding_rounds(id),
    stake_pct REAL,
    source TEXT NOT NULL,
    trust_tier INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS data_conflicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,     -- 'funding_round' or 'ownership'
    company_name TEXT NOT NULL,
    field TEXT NOT NULL,           -- e.g. 'valuation_usd', 'stake_pct_sum'
    details TEXT NOT NULL,         -- human-readable description of the conflicting values
    resolved_value TEXT,
    status TEXT NOT NULL,          -- 'auto_resolved' or 'needs_review'
    resolution_note TEXT NOT NULL
);
