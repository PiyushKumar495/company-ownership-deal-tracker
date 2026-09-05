"""Export the validated dataset and a human-readable reconciliation report."""
import sqlite3
from pathlib import Path

import pandas as pd

OUTPUT_DIR = Path(__file__).parent.parent / "output"


def export_validated_dataset(conn: sqlite3.Connection) -> Path:
    """Write one row per company summarizing what we know and how confident
    we are in it, based on the reconciliation results."""
    query = """
    SELECT
        c.name AS company,
        fr.round_type,
        fr.round_date,
        fr.amount_usd,
        fr.valuation_usd,
        fr.source,
        fr.trust_tier
    FROM funding_rounds fr
    JOIN companies c ON fr.company_id = c.id
    ORDER BY c.name, fr.trust_tier
    """
    df = pd.read_sql_query(query, conn)
    out_path = OUTPUT_DIR / "validated_deals.csv"
    df.to_csv(out_path, index=False)
    return out_path


def export_reconciliation_report(conn: sqlite3.Connection, stats: dict) -> Path:
    conflicts = conn.execute(
        "SELECT * FROM data_conflicts ORDER BY status DESC, company_name"
    ).fetchall()

    lines = [
        "# Reconciliation Report",
        "",
        f"- Valuation conflicts detected: **{stats['valuation_conflicts']}**",
        f"- Ownership conflicts detected: **{stats['ownership_conflicts']}**",
        f"- Total conflict records: **{len(conflicts)}**",
        "",
        "---",
        "",
    ]

    if not conflicts:
        lines.append("No conflicts detected in this run.")
    else:
        for row in conflicts:
            status_label = "NEEDS REVIEW" if row["status"] == "needs_review" else "Auto-resolved"
            lines.append(f"## {row['company_name']} — {row['field']} [{status_label}]")
            lines.append("")
            lines.append(f"**Conflicting values:** {row['details']}")
            lines.append("")
            if row["resolved_value"]:
                lines.append(f"**Resolved value:** {row['resolved_value']}")
                lines.append("")
            lines.append(f"**Reasoning:** {row['resolution_note']}")
            lines.append("")
            lines.append("---")
            lines.append("")

    out_path = OUTPUT_DIR / "reconciliation_report.md"
    out_path.write_text("\n".join(lines))

    # Also write a CSV version for spreadsheet-based review workflows
    if conflicts:
        df = pd.DataFrame([dict(row) for row in conflicts])
        df.to_csv(OUTPUT_DIR / "reconciliation_report.csv", index=False)

    return out_path
