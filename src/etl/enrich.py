"""
Stage 1.5: ENRICH
Calls the YouTube Data API v3 to fetch real video metadata (duration, category,
tags) for each video extracted from Google Takeout.  Uses a local JSON cache so
videos are never re-fetched, saving API quota across pipeline re-runs.

Designed for graceful degradation: if no API key is configured, enrichment is
skipped entirely and the pipeline falls back to keyword-based categorization
and estimated durations in the transform stage.
"""
import json
import logging
import re
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# YouTube assigns every video exactly one of these category IDs.
# Full list: https://developers.google.com/youtube/v3/docs/videoCategories/list
YOUTUBE_CATEGORY_MAP = {
    "1":  ("Film & Animation",    "entertainment"),
    "2":  ("Autos & Vehicles",    "neutral"),
    "10": ("Music",               "neutral"),
    "15": ("Pets & Animals",      "entertainment"),
    "17": ("Sports",              "neutral"),
    "18": ("Short Movies",        "entertainment"),
    "19": ("Travel & Events",     "neutral"),
    "20": ("Gaming",              "entertainment"),
    "21": ("Videoblogging",       "neutral"),
    "22": ("People & Blogs",      "neutral"),
    "23": ("Comedy",              "entertainment"),
    "24": ("Entertainment",       "entertainment"),
    "25": ("News & Politics",     "productive"),
    "26": ("Howto & Style",       "neutral"),
    "27": ("Education",           "productive"),
    "28": ("Science & Technology","productive"),
    "29": ("Nonprofits & Activism","productive"),
    "30": ("Movies",              "entertainment"),
    "31": ("Anime/Animation",     "entertainment"),
    "32": ("Action/Adventure",    "entertainment"),
    "33": ("Classics",            "entertainment"),
    "34": ("Comedy",              "entertainment"),
    "35": ("Documentary",         "productive"),
    "36": ("Drama",               "entertainment"),
    "37": ("Family",              "entertainment"),
    "38": ("Foreign",             "entertainment"),
    "39": ("Horror",              "entertainment"),
    "40": ("Sci-Fi/Fantasy",      "entertainment"),
    "41": ("Thriller",            "entertainment"),
    "42": ("Shorts",              "entertainment"),
    "43": ("Shows",               "entertainment"),
    "44": ("Trailers",            "entertainment"),
}

# Fallback for unknown category IDs
DEFAULT_CATEGORY = ("Unknown", "entertainment")

BATCH_SIZE = 50          # YouTube API allows up to 50 IDs per request
RATE_LIMIT_PAUSE = 0.15  # seconds between API calls (be a good citizen)


# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------

def extract_video_id(url: str) -> str | None:
    """
    Extracts a YouTube video ID from various URL formats found in Takeout:
      - https://www.youtube.com/watch?v=abc123
      - https://youtu.be/abc123
      - https://www.youtube.com/shorts/abc123
      - https://music.youtube.com/watch?v=abc123
      - https://www.youtube.com/watch?v=abc123&list=...
    Returns None if the URL doesn't contain a valid video ID.
    """
    if not isinstance(url, str):
        return None

    parsed = urlparse(url)

    # Standard and music.youtube.com: /watch?v=VIDEO_ID
    if parsed.hostname in ("www.youtube.com", "youtube.com", "m.youtube.com",
                           "music.youtube.com"):
        if parsed.path == "/watch":
            qs = parse_qs(parsed.query)
            vid = qs.get("v", [None])[0]
            return vid if vid else None
        # Shorts: /shorts/VIDEO_ID
        if parsed.path.startswith("/shorts/"):
            return parsed.path.split("/shorts/")[1].split("/")[0].split("?")[0]

    # Short URLs: youtu.be/VIDEO_ID
    if parsed.hostname in ("youtu.be",):
        vid = parsed.path.lstrip("/").split("/")[0].split("?")[0]
        return vid if vid else None

    return None


# ---------------------------------------------------------------------------
# ISO 8601 duration parsing
# ---------------------------------------------------------------------------

def parse_iso8601_duration(iso_duration: str) -> float:
    """
    Converts YouTube's ISO 8601 duration to minutes.
    Examples: 'PT14M23S' -> 14.38,  'PT1H2M3S' -> 62.05,  'PT30S' -> 0.5
    """
    if not iso_duration:
        return 0.0
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_duration)
    if not match:
        return 0.0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return round(hours * 60 + minutes + seconds / 60, 2)


# ---------------------------------------------------------------------------
# Local cache
# ---------------------------------------------------------------------------

def load_cache(cache_path: Path) -> dict:
    """Loads the video metadata cache from disk. Returns empty dict if missing."""
    if cache_path.exists():
        with open(cache_path, "r", encoding="utf-8") as f:
            cache = json.load(f)
        logger.info("Loaded %d cached videos from %s", len(cache), cache_path)
        return cache
    return {}


def save_cache(cache: dict, cache_path: Path):
    """Persists the video metadata cache to disk."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)
    logger.info("Saved %d videos to cache at %s", len(cache), cache_path)


# ---------------------------------------------------------------------------
# YouTube API calls
# ---------------------------------------------------------------------------

def fetch_video_metadata_batch(video_ids: list[str], api_key: str) -> dict:
    """
    Calls the YouTube Data API v3 for a batch of up to 50 video IDs.
    Returns a dict mapping video_id -> {duration_minutes, category_id,
    category_name, productivity_category, tags, title}.

    Videos that are private/deleted/unavailable will simply be absent from
    the response -- callers should handle missing IDs.
    """
    if not video_ids or not api_key:
        return {}

    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {
        "part": "contentDetails,snippet",
        "id": ",".join(video_ids[:BATCH_SIZE]),
        "key": api_key,
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.error("YouTube API request failed: %s", e)
        return {}

    results = {}
    for item in data.get("items", []):
        vid = item["id"]
        duration_iso = item.get("contentDetails", {}).get("duration", "")
        category_id = item.get("snippet", {}).get("categoryId", "")
        tags = item.get("snippet", {}).get("tags", [])
        title = item.get("snippet", {}).get("title", "")

        cat_name, prod_cat = YOUTUBE_CATEGORY_MAP.get(category_id, DEFAULT_CATEGORY)

        results[vid] = {
            "duration_minutes": parse_iso8601_duration(duration_iso),
            "category_id": category_id,
            "category_name": cat_name,
            "productivity_category": prod_cat,
            "tags": tags[:10],  # keep only first 10 tags to limit cache size
            "title": title,
        }

    return results


def fetch_all_videos(video_ids: list[str], api_key: str, cache: dict) -> dict:
    """
    Fetches metadata for all video_ids, using the cache first and only calling
    the API for uncached videos.  Updates and returns the cache dict.
    """
    uncached = [vid for vid in video_ids if vid not in cache]
    if not uncached:
        logger.info("All %d videos found in cache, no API calls needed", len(video_ids))
        return cache

    logger.info(
        "Fetching metadata for %d uncached videos (%d already cached) -- "
        "%d API calls required",
        len(uncached), len(video_ids) - len(uncached),
        (len(uncached) + BATCH_SIZE - 1) // BATCH_SIZE,
    )

    for i in range(0, len(uncached), BATCH_SIZE):
        batch = uncached[i : i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (len(uncached) + BATCH_SIZE - 1) // BATCH_SIZE
        logger.info("  API batch %d/%d  (%d videos)", batch_num, total_batches, len(batch))

        results = fetch_video_metadata_batch(batch, api_key)
        cache.update(results)

        # Mark videos that the API didn't return (deleted/private) so we
        # don't keep re-trying them on every pipeline run
        for vid in batch:
            if vid not in cache:
                cache[vid] = {
                    "duration_minutes": None,
                    "category_id": None,
                    "category_name": None,
                    "productivity_category": None,
                    "tags": [],
                    "title": None,
                    "unavailable": True,
                }

        if i + BATCH_SIZE < len(uncached):
            time.sleep(RATE_LIMIT_PAUSE)

    api_found = sum(1 for vid in uncached if not cache.get(vid, {}).get("unavailable"))
    api_missing = len(uncached) - api_found
    logger.info(
        "API enrichment complete: %d found, %d unavailable (deleted/private)",
        api_found, api_missing,
    )
    return cache


# ---------------------------------------------------------------------------
# Main enrichment function (called from pipeline.py)
# ---------------------------------------------------------------------------

def enrich(df, api_key: str = "", cache_path=None):
    """
    Enriches a raw-extracted DataFrame with real video metadata from YouTube API.

    Adds columns: actual_duration_minutes, youtube_category_id,
    youtube_category_name, yt_productivity_category, api_enriched.

    If api_key is empty, all new columns are set to None / False and the
    transform stage will fall back to keyword categorization + estimated duration.
    """
    import pandas as pd

    # Extract video IDs from URLs
    df = df.copy()
    df["video_id"] = df["video_url"].apply(extract_video_id)

    # Initialize enrichment columns with defaults
    df["actual_duration_minutes"] = None
    df["youtube_category_id"] = None
    df["youtube_category_name"] = None
    df["yt_productivity_category"] = None
    df["api_enriched"] = False

    if not api_key:
        logger.info(
            "No YOUTUBE_API_KEY configured -- skipping API enrichment. "
            "Transform will use keyword-based categorization and estimated durations."
        )
        return df

    # Load cache
    if cache_path is None:
        from config.config import Config
        cache_path = Config.VIDEO_CACHE_PATH

    cache = load_cache(cache_path)

    # Get unique video IDs (skip None / empty)
    unique_ids = [vid for vid in df["video_id"].dropna().unique() if vid]
    logger.info("Found %d unique video IDs to enrich", len(unique_ids))

    # Fetch all (cache-first, then API)
    cache = fetch_all_videos(unique_ids, api_key, cache)
    save_cache(cache, cache_path)

    # Map enriched data back to the DataFrame
    enriched_count = 0
    for idx, row in df.iterrows():
        vid = row["video_id"]
        if vid and vid in cache and not cache[vid].get("unavailable"):
            meta = cache[vid]
            df.at[idx, "actual_duration_minutes"] = meta["duration_minutes"]
            df.at[idx, "youtube_category_id"] = meta["category_id"]
            df.at[idx, "youtube_category_name"] = meta["category_name"]
            df.at[idx, "yt_productivity_category"] = meta["productivity_category"]
            df.at[idx, "api_enriched"] = True
            enriched_count += 1

    logger.info(
        "Enrichment mapped to DataFrame: %d/%d rows enriched (%.1f%%)",
        enriched_count, len(df),
        100 * enriched_count / max(len(df), 1),
    )
    return df


if __name__ == "__main__":
    import pandas as pd
    from config.config import Config
    from src.etl.extract import extract_raw_history

    raw_df = extract_raw_history(Config.RAW_DATA_PATH)
    enriched_df = enrich(raw_df, Config.YOUTUBE_API_KEY, Config.VIDEO_CACHE_PATH)
    print(enriched_df[["video_url", "actual_duration_minutes", "youtube_category_name", "api_enriched"]].head(20))
    print(f"\nEnriched: {enriched_df['api_enriched'].sum()} / {len(enriched_df)}")
