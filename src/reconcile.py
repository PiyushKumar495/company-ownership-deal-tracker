"""
Compares records for the same company across sources, flags conflicts, and
auto-resolves the ones that fall within a tolerance using a source trust
hierarchy. Anything that can't be confidently resolved is marked
'needs_review' rather than guessed.
"""
import sqlite3
from typing import Optional

VALUATION_CONFLICT_THRESHOLD = 0.08  # 8% relative difference triggers a flag
OWNERSHIP_OVERSUBSCRIPTION_THRESHOLD = 100.0

# Lower number = more trusted
TRUST_RANK = {
    "company_filing": 1,
    "press_release": 1,
    "news_aggregator": 3,
    "ai_extracted": 4,
}


def _relative_diff(a: float, b: float) -> float:
    if a == 0 and b == 0:
        return 0.0
    return abs(a - b) / max(abs(a), abs(b))


def reconcile_valuations(conn: sqlite3.Connection) -> int:
    """Find companies with multiple, materially different valuation figures
    reported across sources and log a conflict record for each."""
    companies = conn.execute("SELECT id, name FROM companies").fetchall()
    conflicts_found = 0

    for company in companies:
        rows = conn.execute(
            """SELECT valuation_usd, source, trust_tier FROM funding_rounds
               WHERE company_id = ? AND valuation_usd IS NOT NULL""",
            (company["id"],),
        ).fetchall()

        if len(rows) < 2:
            continue

        values = [(r["valuation_usd"], r["source"], r["trust_tier"]) for r in rows]
        max_val = max(v[0] for v in values)
        min_val = min(v[0] for v in values)

        if _relative_diff(max_val, min_val) <= VALUATION_CONFLICT_THRESHOLD:
            continue  # close enough, not worth flagging

        conflicts_found += 1
        # Prefer the most-trusted source (lowest trust_tier number); if tied,
        # this stays ambiguous and needs a human.
        best = sorted(values, key=lambda v: v[2])
        most_trusted_tier = best[0][2]
        candidates_at_best_tier = [v for v in values if v[2] == most_trusted_tier]

        details = "; ".join(f"{src}=${val:,.0f}" for val, src, _ in values)

        if len(candidates_at_best_tier) == 1:
            resolved_value = candidates_at_best_tier[0][0]
            status = "auto_resolved"
            note = (
                f"Valuation figures disagree by "
                f"{_relative_diff(max_val, min_val):.0%}. Resolved to the most-trusted "
                f"source ({candidates_at_best_tier[0][1]}: ${resolved_value:,.0f})."
            )
        else:
            resolved_value = None
            status = "needs_review"
            note = (
                f"Valuation figures disagree by {_relative_diff(max_val, min_val):.0%} "
                f"and multiple sources share the same trust tier, so this cannot be "
                f"auto-resolved. Values found: {details}."
            )

        conn.execute(
            """INSERT INTO data_conflicts (entity_type, company_name, field, details, resolved_value, status, resolution_note)
               VALUES ('funding_round', ?, 'valuation_usd', ?, ?, ?, ?)""",
            (company["name"], details, str(resolved_value) if resolved_value else None, status, note),
        )

    conn.commit()
    return conflicts_found


def reconcile_ownership(conn: sqlite3.Connection) -> int:
    """Flag companies whose summed reported ownership stakes exceed 100% --
    a common symptom of duplicate or conflicting ownership records."""
    companies = conn.execute("SELECT id, name FROM companies").fetchall()
    conflicts_found = 0

    for company in companies:
        rows = conn.execute(
            """SELECT investors.name AS investor, ownership.stake_pct, ownership.source
               FROM ownership JOIN investors ON ownership.investor_id = investors.id
               WHERE ownership.company_id = ? AND ownership.stake_pct IS NOT NULL""",
            (company["id"],),
        ).fetchall()

        if not rows:
            continue

        total = sum(r["stake_pct"] for r in rows)
        if total <= OWNERSHIP_OVERSUBSCRIPTION_THRESHOLD:
            continue

        conflicts_found += 1
        details = "; ".join(f"{r['investor']}={r['stake_pct']}% ({r['source']})" for r in rows)
        note = (
            f"Summed reported ownership stakes total {total:.0f}%, which exceeds 100%. "
            f"This usually means overlapping rounds are being summed together, a stake "
            f"was diluted but the record wasn't updated, or one source's figure is wrong. "
            f"Needs manual review against primary sources before publishing."
        )

        conn.execute(
            """INSERT INTO data_conflicts (entity_type, company_name, field, details, resolved_value, status, resolution_note)
               VALUES ('ownership', ?, 'stake_pct_sum', ?, NULL, 'needs_review', ?)""",
            (company["name"], details, note),
        )

    conn.commit()
    return conflicts_found


def run_all(conn: sqlite3.Connection) -> dict:
    valuation_conflicts = reconcile_valuations(conn)
    ownership_conflicts = reconcile_ownership(conn)
    return {
        "valuation_conflicts": valuation_conflicts,
        "ownership_conflicts": ownership_conflicts,
    }
