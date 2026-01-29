import os
from dataclasses import dataclass
from typing import List, Tuple


def _split_csv(value: str) -> List[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    # Core
    database_url: str = os.getenv("DATABASE_URL", "postgresql://postgres:eventpulse@localhost:5432/eventpulse")
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # Paths
    raw_data_dir: str = os.getenv("RAW_DATA_DIR", "/data/raw")
    contracts_dir: str = os.getenv("CONTRACTS_DIR", "/data/contracts")
    incoming_dir: str = os.getenv("INCOMING_DIR", "/data/incoming")
    archive_dir: str = os.getenv("ARCHIVE_DIR", "/data/archive")

    # Controls
    drift_policy_default: str = os.getenv("DRIFT_POLICY_DEFAULT", "warn").lower()  # warn|fail|allow
    max_file_mb: int = int(os.getenv("MAX_FILE_MB", "50"))
    allowed_file_exts: Tuple[str, ...] = tuple(_split_csv(os.getenv("ALLOWED_FILE_EXTS", ".csv,.xlsx,.xls")))

    # Watcher
    watch_poll_seconds: int = int(os.getenv("WATCH_POLL_SECONDS", "3"))

    # Logging
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()


settings = Settings()
