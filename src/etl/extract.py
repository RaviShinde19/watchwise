"""
Stage 1: EXTRACT
Reads the raw YouTube watch-history export (Google Takeout JSON format) into a
pandas DataFrame with minimal processing -- just flattening the nested JSON.
"""
import json
import logging
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def extract_raw_history(raw_path: Path) -> pd.DataFrame:
    """
    Reads a Google Takeout `watch-history.json` file and returns a flat DataFrame.

    Some entries in a real export are ads or removed videos and won't have a
    `subtitles` (channel) field -- those are kept but the channel columns are null,
    and are filtered out during transform.
    """
    if not Path(raw_path).exists():
        raise FileNotFoundError(
            f"Raw data file not found at {raw_path}. "
            f"Run `python src/generate_sample_data.py` to create a sample, "
            f"or export your real history via Google Takeout."
        )

    with open(raw_path, "r", encoding="utf-8") as f:
        raw_events = json.load(f)

    logger.info("Extracted %d raw events from %s", len(raw_events), raw_path)

    records = []
    for event in raw_events:
        subtitles = event.get("subtitles", [{}])
        channel_name = subtitles[0].get("name") if subtitles else None
        channel_url = subtitles[0].get("url") if subtitles else None

        records.append(
            {
                "video_title_raw": event.get("title"),
                "video_url": event.get("titleUrl"),
                "channel_name": channel_name,
                "channel_url": channel_url,
                "watch_time_raw": event.get("time"),
                "product": ",".join(event.get("products", [])),
            }
        )

    df = pd.DataFrame(records)
    return df


if __name__ == "__main__":
    from config.config import Config

    df = extract_raw_history(Config.RAW_DATA_PATH)
    print(df.head())
    print(f"\nTotal rows extracted: {len(df)}")
