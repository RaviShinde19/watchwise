"""
Stage 2: TRANSFORM
Cleans the raw extracted data and enriches it with derived, analysis-ready columns:
  - proper datetime parsing (+ local hour/day-of-week/date breakdown)
  - cleaned video title (strips the "Watched " prefix Takeout adds)
  - productivity category: uses YouTube's official category from API enrichment
    when available, falls back to keyword-based channel-name matching otherwise
  - watch_minutes: uses real video duration from API when available, falls back
    to a 6-minute estimate otherwise
  - session_id: groups videos into "binge sessions" when gaps between
    consecutive watches are under SESSION_GAP_MINUTES
"""
import logging

import pandas as pd

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SESSION_GAP_MINUTES = 10

# Keyword rules used as FALLBACK when YouTube API category is unavailable.
# These are only used for videos where api_enriched == False (deleted/private
# videos, or when no API key is configured).
PRODUCTIVE_KEYWORDS = [
    "tutorial", "course", "engineering", "code", "coding", "dojo", "camp",
    "docs", "airflow", "sql", "python", "data", "system design", "science",
    "veritasium", "fireship", "documentary", "news", "lecture", "university",
]
NEUTRAL_KEYWORDS = [
    "podcast", "lofi", "music", "vlog", "review", "mkbhd", "unboxing",
]
# Anything not matched by the two lists above defaults to "entertainment".


def categorize_channel(channel_name: str) -> str:
    """Keyword-based categorization. Used as fallback when API data is unavailable."""
    if not isinstance(channel_name, str):
        return "unknown"
    name = channel_name.lower()
    if any(kw in name for kw in PRODUCTIVE_KEYWORDS):
        return "productive"
    if any(kw in name for kw in NEUTRAL_KEYWORDS):
        return "neutral"
    return "entertainment"


def clean_title(raw_title: str) -> str:
    if not isinstance(raw_title, str):
        return raw_title
    return raw_title[len("Watched "):] if raw_title.startswith("Watched ") else raw_title


def assign_sessions(df: pd.DataFrame) -> pd.Series:
    """
    Assigns an incrementing session_id per row: a new session starts whenever the
    gap since the previous watch event exceeds SESSION_GAP_MINUTES. Used to detect
    binge-watching sequences downstream in SQL.
    """
    df = df.sort_values("watch_datetime").reset_index(drop=True)
    gap = df["watch_datetime"].diff().dt.total_seconds().div(60)
    new_session = (gap.isna()) | (gap > SESSION_GAP_MINUTES)
    return new_session.cumsum()


def resolve_productivity_category(row) -> str:
    """
    Determines the final productivity category for a row.
    Priority: YouTube API category > keyword-based channel name matching.
    """
    # If API enrichment provided a category, use it
    if row.get("api_enriched") and pd.notna(row.get("yt_productivity_category")):
        return row["yt_productivity_category"]
    # Fallback to keyword matching on channel name
    return categorize_channel(row.get("channel_name", ""))


def resolve_watch_minutes(row) -> float:
    """
    Determines the watch duration for a row.
    Uses real API duration when available, otherwise estimates 6 minutes.
    """
    if row.get("api_enriched") and pd.notna(row.get("actual_duration_minutes")):
        duration = row["actual_duration_minutes"]
        # Sanity check: cap at 12 hours (livestream replays can be very long)
        return min(float(duration), 720.0) if duration > 0 else 6.0
    return 6.0


def transform(df: pd.DataFrame) -> pd.DataFrame:
    initial_count = len(df)

    # Drop events with no channel (ads / removed videos) and no timestamp
    df = df.dropna(subset=["channel_name", "watch_time_raw"]).copy()

    # Drop exact duplicate rows (Takeout exports can contain dupes)
    df = df.drop_duplicates(subset=["video_url", "watch_time_raw"])

    # Parse timestamp -> proper datetime, drop unparseable rows
    df["watch_datetime"] = pd.to_datetime(df["watch_time_raw"], errors="coerce", utc=True)
    df = df.dropna(subset=["watch_datetime"])

    # Clean fields
    df["video_title"] = df["video_title_raw"].apply(clean_title)

    # --- Productivity category: API-first, keyword-fallback ---
    df["productivity_category"] = df.apply(resolve_productivity_category, axis=1)

    # --- Watch duration: real API duration when available, else 6 min ---
    df["watch_minutes"] = df.apply(resolve_watch_minutes, axis=1)

    # Ensure api_enriched column exists (might be missing if enrich step was skipped)
    if "api_enriched" not in df.columns:
        df["api_enriched"] = False

    # YouTube category info (may be None if not enriched)
    for col in ["youtube_category_id", "youtube_category_name"]:
        if col not in df.columns:
            df[col] = None

    # Time-based derived fields
    df["watch_date"] = df["watch_datetime"].dt.date
    df["watch_hour"] = df["watch_datetime"].dt.hour
    df["day_of_week"] = df["watch_datetime"].dt.day_name()
    df["is_weekend"] = df["watch_datetime"].dt.dayofweek >= 5

    # Session assignment for binge detection
    df["session_id"] = assign_sessions(df)

    final_cols = [
        "video_title", "video_url", "channel_name", "channel_url",
        "watch_datetime", "watch_date", "watch_hour", "day_of_week",
        "is_weekend", "productivity_category", "session_id",
        "watch_minutes", "api_enriched",
        "youtube_category_id", "youtube_category_name",
    ]
    df = df[final_cols].sort_values("watch_datetime").reset_index(drop=True)

    api_count = df["api_enriched"].sum()
    logger.info(
        "Transform complete: %d -> %d rows (%d dropped as invalid/duplicate). "
        "API-enriched: %d (%.1f%%), keyword-fallback: %d",
        initial_count, len(df), initial_count - len(df),
        api_count, 100 * api_count / max(len(df), 1),
        len(df) - api_count,
    )
    return df


if __name__ == "__main__":
    from config.config import Config
    from src.etl.extract import extract_raw_history

    raw_df = extract_raw_history(Config.RAW_DATA_PATH)
    clean_df = transform(raw_df)
    print(clean_df.head(10))
    print(f"\nProductivity category breakdown:\n{clean_df['productivity_category'].value_counts()}")
    print(f"\nWatch minutes stats:\n{clean_df['watch_minutes'].describe()}")
    print(f"\nAPI enriched: {clean_df['api_enriched'].sum()} / {len(clean_df)}")
