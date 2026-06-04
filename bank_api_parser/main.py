#!/usr/bin/env python3
"""
Bank API Portal Parser
Entry point: python main.py [--banks tbank tochka alfabank sber] [--no-diff] [--date YYYY-MM-DD]
"""
import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# ── Logging setup (must happen before any parser import) ──────────────────────

LOG_FILE = Path(__file__).parent / "parser.log"


def setup_logging(debug: bool = False):
    level = logging.DEBUG if debug else logging.INFO
    fmt = "%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s"

    root = logging.getLogger()
    root.setLevel(level)

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level)
    ch.setFormatter(logging.Formatter(fmt))
    root.addHandler(ch)

    # File handler
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(fmt))
    root.addHandler(fh)

    # Silence noisy third-party loggers
    for lib in ("urllib3", "playwright", "asyncio", "websockets"):
        logging.getLogger(lib).setLevel(logging.WARNING)


# ─────────────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(description="Bank API portal parser")
    parser.add_argument(
        "--banks",
        nargs="*",
        default=["tbank", "tochka", "alfabank", "sber"],
        choices=["tbank", "tochka", "alfabank", "sber"],
        help="Banks to parse (default: all)",
    )
    parser.add_argument("--no-diff", action="store_true", help="Skip diff calculation")
    parser.add_argument("--no-excel", action="store_true", help="Skip Excel export")
    parser.add_argument("--debug", action="store_true", help="Enable DEBUG logging")
    parser.add_argument("--date", default=None, help="Override snapshot date (YYYY-MM-DD)")
    return parser.parse_args()


def run_parser(bank_name: str):
    """Instantiate and run the appropriate parser for a bank."""
    from parsers.tbank_parser import TBankParser
    from parsers.tochka_parser import TochkaParser
    from parsers.alfabank_parser import AlfaBankParser
    from parsers.sber_parser import SberParser

    parsers = {
        "tbank": TBankParser,
        "tochka": TochkaParser,
        "alfabank": AlfaBankParser,
        "sber": SberParser,
    }
    cls = parsers.get(bank_name)
    if cls is None:
        logging.getLogger("main").error("Unknown bank: %s", bank_name)
        return None

    return cls().parse()


def main():
    args = parse_args()
    setup_logging(args.debug)
    logger = logging.getLogger("main")

    logger.info("=" * 70)
    logger.info("Bank API Parser starting | banks: %s", args.banks)
    logger.info("=" * 70)

    from storage.snapshot_manager import SnapshotManager
    from storage.diff_engine import DiffEngine
    from exporters.excel_exporter import ExcelExporter

    snapshot_mgr = SnapshotManager()
    diff_engine = DiffEngine()
    exporter = ExcelExporter()

    snapshots: dict = {}
    diffs = []

    for bank in args.banks:
        logger.info("─" * 50)
        logger.info("Processing bank: %s", bank.upper())

        snapshot = None
        try:
            snapshot = run_parser(bank)
        except Exception as exc:
            logger.error("Unhandled exception for %s: %s", bank, exc, exc_info=True)

        snapshots[bank] = snapshot

        if snapshot:
            saved_path = snapshot_mgr.save(snapshot, date=args.date)
            logger.info("Saved snapshot: %s", saved_path)

            if not args.no_diff:
                prev = snapshot_mgr.load_previous(bank)
                if prev:
                    diff = diff_engine.compare(prev, snapshot)
                    if diff:
                        diffs.append(diff)
                        logger.info("\n%s", diff.summary_text())
                else:
                    logger.info("[%s] No previous snapshot found — skipping diff", bank)
        else:
            logger.error("Parser returned no data for %s", bank)

    logger.info("─" * 50)
    logger.info("Parsing complete. Results:")
    for bank, snap in snapshots.items():
        if snap:
            logger.info("  %-12s %3d services  %4d methods", bank, snap.total_services, snap.total_methods)
        else:
            logger.info("  %-12s FAILED", bank)

    active_diffs = [d for d in diffs if d and d.has_changes]

    if not args.no_excel:
        try:
            xlsx_path = exporter.export(
                snapshots,
                diffs=active_diffs if active_diffs else None,
            )
            logger.info("Excel report: %s", xlsx_path)
        except Exception as exc:
            logger.error("Excel export failed: %s", exc, exc_info=True)

    if active_diffs:
        logger.info("─" * 50)
        logger.info("Changes detected in %d bank(s):", len(active_diffs))
        for diff in active_diffs:
            logger.info("\n%s", diff.summary_text())
    elif diffs:
        logger.info("No API changes detected between snapshots")

    success_count = sum(1 for s in snapshots.values() if s is not None)
    logger.info("=" * 70)
    logger.info("Done: %d/%d banks parsed successfully", success_count, len(args.banks))

    # Generate dashboard
    try:
        import subprocess
        dashboard_script = Path(__file__).parent / "generate_dashboard.sh"
        if dashboard_script.exists():
            result = subprocess.run(
                ["bash", str(dashboard_script)],
                cwd=Path(__file__).parent,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                logger.info("Dashboard updated: %s", Path(__file__).parent / "dashboard" / "index.html")
            else:
                logger.warning("Dashboard generation failed: %s", result.stderr)
    except Exception as exc:
        logger.warning("Dashboard generation skipped: %s", exc)

    return 0 if success_count > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
