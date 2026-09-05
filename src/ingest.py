"""Load raw sources (structured CSV + unstructured press-release JSON) and
normalize them into the SQLite schema, preserving every source's version of
each fact."""
import csv
import json
import sqlite3
from pathlib import Path
from typing import Optional

from src.ai_extract import extract_deal_fields
from src.db import get_or_create_company, get_or_create_investor

DATA_DIR = Path(__file__).parent.parent / "data" / "raw"

TRUST_TIERS = {
    "company_filing": 1,
    "press_release": 1,
    "news_aggregator": 3,
    "ai_extracted": 4,
}


def ingest_structured_csv(conn: sqlite3.Connection, filename: str) -> int:
    """Ingest a structured CSV of company/investor/round/ownership facts.

    Multiple CSV rows can describe the same round (one row per investor), so
    rounds are deduplicated on (company, round_date, source) within this
    ingest call -- each distinct round gets exactly one funding_rounds row,
    and every investor row attaches its ownership stake to that same round.
    """
    path = DATA_DIR / filename
    count = 0
    round_cache: dict = {}  # (company_id, round_date, source) -> round_id

    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            company_id = get_or_create_company(conn, row["company"])
            investor_id = get_or_create_investor(conn, row["investor"])
            source = row["source"]
            trust_tier = TRUST_TIERS.get(source, 5)

            amount = float(row["amount_usd"]) if row.get("amount_usd") else None
            valuation = float(row["valuation_usd"]) if row.get("valuation_usd") else None

            round_key = (company_id, row.get("round_date"), source)
            if round_key in round_cache:
                round_id = round_cache[round_key]
            else:
                cur = conn.execute(
                    """INSERT INTO funding_rounds
                       (company_id, round_type, round_date, amount_usd, valuation_usd, source, trust_tier, raw_reference)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (company_id, row.get("round_type"), row.get("round_date"), amount,
                     valuation, source, trust_tier, filename),
                )
                round_id = cur.lastrowid
                round_cache[round_key] = round_id
                count += 1

            stake_pct = float(row["stake_pct"]) if row.get("stake_pct") else None
            if stake_pct is not None:
                conn.execute(
                    """INSERT INTO ownership (company_id, investor_id, round_id, stake_pct, source, trust_tier)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (company_id, investor_id, round_id, stake_pct, source, trust_tier),
                )
    conn.commit()
    return count


def ingest_press_releases(conn: sqlite3.Connection, filename: str, use_ai: bool = True) -> int:
    """Ingest unstructured press-release text, running it through the
    extractor (AI or fallback) to pull structured fields before loading."""
    path = DATA_DIR / filename
    with open(path) as f:
        records = json.load(f)

    count = 0
    for record in records:
        source = record["source"]
        trust_tier = record.get("trust_tier", TRUST_TIERS.get(source, 5))
        extracted = extract_deal_fields(record["text"], use_ai=use_ai)

        if not extracted.get("company"):
            print(f"[ingest] Could not identify a company in record from {filename}; skipping.")
            continue

        company_id = get_or_create_company(conn, extracted["company"])

        cur = conn.execute(
            """INSERT INTO funding_rounds
               (company_id, round_type, round_date, amount_usd, valuation_usd, source, trust_tier, raw_reference)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                company_id,
                extracted.get("round_type"),
                extracted.get("round_date") or record.get("published_date"),
                extracted.get("amount_usd"),
                extracted.get("valuation_usd"),
                source,
                trust_tier,
                filename,
            ),
        )
        round_id = cur.lastrowid

        for stake in extracted.get("stakes", []):
            investor_id = get_or_create_investor(conn, stake["investor"])
            conn.execute(
                """INSERT INTO ownership (company_id, investor_id, round_id, stake_pct, source, trust_tier)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (company_id, investor_id, round_id, stake.get("stake_pct"), source, trust_tier),
            )
        count += 1
    conn.commit()
    return count
