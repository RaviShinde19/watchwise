"""
Unit tests for the YouTube API enrichment module. Tests URL parsing,
duration conversion, category mapping, and graceful degradation without
an API key. Run with:
    PYTHONPATH=. python -m pytest tests/ -v
"""
import pandas as pd
import pytest

from src.etl.enrich import (
    extract_video_id,
    parse_iso8601_duration,
    YOUTUBE_CATEGORY_MAP,
    DEFAULT_CATEGORY,
)


# ---------------------------------------------------------------------------
# Video ID extraction from various URL formats
# ---------------------------------------------------------------------------

class TestExtractVideoId:
    def test_standard_url(self):
        url = "https://www.youtube.com/watch?v=HYygGaIUSqI"
        assert extract_video_id(url) == "HYygGaIUSqI"

    def test_url_with_extra_params(self):
        url = "https://www.youtube.com/watch?v=abc123&list=PLxyz&index=5"
        assert extract_video_id(url) == "abc123"

    def test_short_url(self):
        url = "https://youtu.be/HYygGaIUSqI"
        assert extract_video_id(url) == "HYygGaIUSqI"

    def test_shorts_url(self):
        url = "https://www.youtube.com/shorts/dQw4w9WgXcQ"
        assert extract_video_id(url) == "dQw4w9WgXcQ"

    def test_music_url(self):
        url = "https://music.youtube.com/watch?v=abc123"
        assert extract_video_id(url) == "abc123"

    def test_mobile_url(self):
        url = "https://m.youtube.com/watch?v=abc123"
        assert extract_video_id(url) == "abc123"

    def test_none_url(self):
        assert extract_video_id(None) is None

    def test_empty_string(self):
        assert extract_video_id("") is None

    def test_non_youtube_url(self):
        assert extract_video_id("https://example.com/watch?v=abc") is None

    def test_url_without_video_id(self):
        assert extract_video_id("https://www.youtube.com/") is None


# ---------------------------------------------------------------------------
# ISO 8601 duration parsing
# ---------------------------------------------------------------------------

class TestParseIsoDuration:
    def test_minutes_and_seconds(self):
        assert parse_iso8601_duration("PT14M23S") == 14.38

    def test_hours_minutes_seconds(self):
        assert parse_iso8601_duration("PT1H2M3S") == 62.05

    def test_seconds_only(self):
        assert parse_iso8601_duration("PT30S") == 0.5

    def test_minutes_only(self):
        assert parse_iso8601_duration("PT5M") == 5.0

    def test_hours_only(self):
        assert parse_iso8601_duration("PT2H") == 120.0

    def test_empty_string(self):
        assert parse_iso8601_duration("") == 0.0

    def test_none(self):
        assert parse_iso8601_duration(None) == 0.0

    def test_short_video(self):
        # YouTube Shorts are typically 15-60 seconds
        assert parse_iso8601_duration("PT15S") == 0.25

    def test_long_livestream(self):
        assert parse_iso8601_duration("PT3H45M10S") == 225.17


# ---------------------------------------------------------------------------
# Category mapping
# ---------------------------------------------------------------------------

class TestCategoryMapping:
    def test_education_is_productive(self):
        _, prod = YOUTUBE_CATEGORY_MAP["27"]
        assert prod == "productive"

    def test_science_tech_is_productive(self):
        _, prod = YOUTUBE_CATEGORY_MAP["28"]
        assert prod == "productive"

    def test_gaming_is_entertainment(self):
        _, prod = YOUTUBE_CATEGORY_MAP["20"]
        assert prod == "entertainment"

    def test_music_is_neutral(self):
        _, prod = YOUTUBE_CATEGORY_MAP["10"]
        assert prod == "neutral"

    def test_default_category(self):
        _, prod = DEFAULT_CATEGORY
        assert prod == "entertainment"

    def test_unknown_id_uses_default(self):
        result = YOUTUBE_CATEGORY_MAP.get("9999", DEFAULT_CATEGORY)
        assert result == DEFAULT_CATEGORY


# ---------------------------------------------------------------------------
# Graceful degradation without API key
# ---------------------------------------------------------------------------

class TestEnrichGraceful:
    def test_enrich_without_api_key_adds_columns(self):
        from src.etl.enrich import enrich

        df = pd.DataFrame([{
            "video_title_raw": "Watched Test Video",
            "video_url": "https://www.youtube.com/watch?v=abc123",
            "channel_name": "Test Channel",
            "channel_url": "https://www.youtube.com/c/test",
            "watch_time_raw": "2024-01-01T10:00:00.000Z",
            "product": "YouTube",
        }])
        result = enrich(df, api_key="", cache_path=None)

        # Should add enrichment columns with None/False defaults
        assert "actual_duration_minutes" in result.columns
        assert "youtube_category_id" in result.columns
        assert "api_enriched" in result.columns
        assert result.iloc[0]["api_enriched"] == False
