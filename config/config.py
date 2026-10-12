"""
Central configuration for the pipeline. All values are environment-driven so the
same code runs unchanged locally, in Airflow, or in CI.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Resolve project root regardless of where the code is invoked from
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


class Config:
    PROJECT_ROOT = PROJECT_ROOT

    # --- Database ---
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = os.getenv("DB_PORT", "5433")
    DB_NAME = os.getenv("DB_NAME", "youtube_analytics")
    DB_USER = os.getenv("DB_USER", "postgres")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")

    @classmethod
    def sqlalchemy_uri(cls) -> str:
        return (
            f"postgresql+psycopg2://{cls.DB_USER}:{cls.DB_PASSWORD}"
            f"@{cls.DB_HOST}:{cls.DB_PORT}/{cls.DB_NAME}"
        )

    # --- YouTube Data API v3 ---
    YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
    ENRICH_WITH_API = bool(YOUTUBE_API_KEY)  # auto-enable if key is set

    # --- File paths ---
    RAW_DATA_PATH = PROJECT_ROOT / os.getenv("RAW_DATA_PATH", "data/watch-history.json")
    STAGED_DATA_PATH = PROJECT_ROOT / os.getenv(
        "STAGED_DATA_PATH", "data/staged_watch_history.csv"
    )
    VIDEO_CACHE_PATH = PROJECT_ROOT / os.getenv(
        "VIDEO_CACHE_PATH", "data/video_cache.json"
    )
    SQL_DIR = PROJECT_ROOT / "sql"
