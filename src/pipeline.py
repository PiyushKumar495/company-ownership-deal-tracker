"""Run the full pipeline: ingest -> reconcile -> export."""
import os
from pathlib import Path

from src.db import get_connection, init_db
from src.ingest import ingest_structured_csv, ingest_press_releases
from src.reconcile import run_all
from src.export_report import export_validated_dataset, export_reconciliation_report

OUTPUT_DIR = Path(__file__).parent.parent / "output"
DB_PATH = OUTPUT_DIR / "deal_tracker.db"


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()  # start clean each run

    use_ai = bool(os.environ.get("ANTHROPIC_API_KEY"))
    print(f"[pipeline] AI extraction {'ENABLED' if use_ai else 'DISABLED (no ANTHROPIC_API_KEY, using fallback extractor)'}")

    conn = get_connection(str(DB_PATH))
    init_db(conn)

    print("[pipeline] Ingesting structured filings...")
    n_structured = ingest_structured_csv(conn, "filings_source_c.csv")
    print(f"  -> {n_structured} rows")

    print("[pipeline] Ingesting unstructured press releases (source A)...")
    n_a = ingest_press_releases(conn, "press_release_source_a.json", use_ai=use_ai)
    print(f"  -> {n_a} rounds extracted")

    print("[pipeline] Ingesting unstructured press releases (source B)...")
    n_b = ingest_press_releases(conn, "press_release_source_b.json", use_ai=use_ai)
    print(f"  -> {n_b} rounds extracted")

    print("[pipeline] Reconciling conflicts...")
    stats = run_all(conn)
    print(f"  -> {stats}")

    print("[pipeline] Exporting outputs...")
    dataset_path = export_validated_dataset(conn)
    report_path = export_reconciliation_report(conn, stats)
    print(f"  -> {dataset_path}")
    print(f"  -> {report_path}")

    conn.close()
    print("[pipeline] Done.")


if __name__ == "__main__":
    main()
