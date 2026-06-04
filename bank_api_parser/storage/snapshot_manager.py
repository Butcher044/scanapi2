import json
import logging
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from parsers.base_parser import ParseSnapshot

logger = logging.getLogger("storage.snapshot_manager")

SNAPSHOTS_DIR = Path(__file__).parent.parent / "snapshots"
KEEP_DAYS = 2  # Keep today (N) and yesterday (N-1); delete N-2 and older


class SnapshotManager:
    def __init__(self, base_dir: Path = SNAPSHOTS_DIR):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, snapshot: ParseSnapshot, date: Optional[str] = None) -> Path:
        """Save a snapshot to disk. date = 'YYYY-MM-DD' (defaults to today UTC)."""
        date_str = date or datetime.utcnow().strftime("%Y-%m-%d")
        day_dir = self.base_dir / date_str
        day_dir.mkdir(parents=True, exist_ok=True)

        file_path = day_dir / f"{snapshot.bank}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(snapshot.to_dict(), f, ensure_ascii=False, indent=2)

        logger.info("Snapshot saved: %s", file_path)
        self._cleanup_old_snapshots()
        return file_path

    def load(self, bank: str, date: Optional[str] = None) -> Optional[ParseSnapshot]:
        """Load snapshot for a bank on a given date (defaults to today UTC)."""
        date_str = date or datetime.utcnow().strftime("%Y-%m-%d")
        file_path = self.base_dir / date_str / f"{bank}.json"

        if not file_path.exists():
            logger.debug("Snapshot not found: %s", file_path)
            return None

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return ParseSnapshot.from_dict(data)

    def load_previous(self, bank: str) -> Optional[ParseSnapshot]:
        """Load the most recent snapshot older than today."""
        today = datetime.utcnow().strftime("%Y-%m-%d")

        existing_dates = sorted(
            [d.name for d in self.base_dir.iterdir() if d.is_dir() and d.name != today],
            reverse=True,
        )

        for date_str in existing_dates:
            snapshot = self.load(bank, date_str)
            if snapshot is not None:
                logger.debug("Found previous snapshot for %s on %s", bank, date_str)
                return snapshot

        return None

    def list_dates(self) -> list:
        """Return sorted list of dates with snapshots (newest first)."""
        if not self.base_dir.exists():
            return []
        return sorted(
            [d.name for d in self.base_dir.iterdir() if d.is_dir()],
            reverse=True,
        )

    def _cleanup_old_snapshots(self):
        """Remove snapshot directories older than KEEP_DAYS."""
        today = datetime.utcnow().date()
        cutoff = today - timedelta(days=KEEP_DAYS - 1)

        for day_dir in list(self.base_dir.iterdir()):
            if not day_dir.is_dir():
                continue
            try:
                dir_date = datetime.strptime(day_dir.name, "%Y-%m-%d").date()
                if dir_date < cutoff:
                    shutil.rmtree(day_dir)
                    logger.info("Deleted old snapshot dir: %s", day_dir)
            except ValueError:
                pass
