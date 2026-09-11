"""
Unit tests for the transform stage. Run with:
    PYTHONPATH=. python -m pytest tests/ -v
"""
import pandas as pd
import pytest

from src.etl.transform import categorize_channel, clean_title, transform


def test_categorize_channel_productive():
    assert categorize_channel("freeCodeCamp") == "productive"
    assert categorize_channel("Python Data Science Tutorials") == "productive"


def test_categorize_channel_entertainment_default():
    assert categorize_channel("Some Random Gaming Channel") == "entertainment"


def test_categorize_channel_handles_none():
    assert categorize_channel(None) == "unknown"


def test_clean_title_strips_prefix():
    assert clean_title("Watched My Cool Video") == "My Cool Video"
    assert clean_title("No Prefix Here") == "No Prefix Here"


def _make_raw_row(title="Watched Video A", url="https://youtube.com/watch?v=1",
                  channel="freeCodeCamp", time="2024-01-01T10:00:00.000Z", **extra):
    """Helper to build a raw row dict with optional overrides."""
    row = {
        "video_title_raw": title,
        "video_url": url,
        "channel_name": channel,
        "channel_url": "https://youtube.com/c/fcc",
        "watch_time_raw": time,
        "product": "YouTube",
    }
    row.update(extra)
    return row


def test_transform_drops_rows_without_channel():
    raw = pd.DataFrame([
        _make_raw_row(),
        _make_raw_row(channel=None, url="https://youtube.com/watch?v=2",
                      time="2024-01-01T11:00:00.000Z"),
    ])
    result = transform(raw)
    assert len(result) == 1
    assert result.iloc[0]["productivity_category"] == "productive"


def test_transform_deduplicates():
    raw = pd.DataFrame([_make_raw_row()] * 3)
    result = transform(raw)
    assert len(result) == 1


def test_transform_uses_api_category_when_available():
    """When API enrichment provides a category, it should override keyword matching."""
    raw = pd.DataFrame([
        _make_raw_row(
            channel="SomeRandomChannel",  # keyword match would say "entertainment"
            api_enriched=True,
            yt_productivity_category="productive",  # but API says productive
            actual_duration_minutes=14.5,
            youtube_category_id="27",
            youtube_category_name="Education",
        ),
    ])
    result = transform(raw)
    assert result.iloc[0]["productivity_category"] == "productive"
    assert result.iloc[0]["watch_minutes"] == 14.5


def test_transform_falls_back_to_keyword_without_api():
    """Without API data, should use keyword-based categorization and 6 min estimate."""
    raw = pd.DataFrame([_make_raw_row(channel="freeCodeCamp")])
    result = transform(raw)
    assert result.iloc[0]["productivity_category"] == "productive"
    assert result.iloc[0]["watch_minutes"] == 6.0
    assert result.iloc[0]["api_enriched"] == False


def test_transform_output_columns():
    """Verify all expected columns are in the output."""
    raw = pd.DataFrame([_make_raw_row()])
    result = transform(raw)
    expected_cols = {
        "video_title", "video_url", "channel_name", "channel_url",
        "watch_datetime", "watch_date", "watch_hour", "day_of_week",
        "is_weekend", "productivity_category", "session_id",
        "watch_minutes", "api_enriched",
        "youtube_category_id", "youtube_category_name",
    }
    assert expected_cols.issubset(set(result.columns))
