-- ============================================================================
-- Analytical queries for the YouTube Productivity Analyzer.
-- Each query is labeled with a name comment so report.py can parse and run
-- them individually by name (see parse_named_queries in src/analysis/report.py).
-- ============================================================================

-- name: peak_usage_hour
-- Hour of day (0-23) with the most watch events overall
SELECT
    watch_hour,
    COUNT(*) AS event_count,
    SUM(watch_minutes) AS total_minutes
FROM fact_watch_events
GROUP BY watch_hour
ORDER BY event_count DESC;

-- name: productivity_ratio
-- Daily split of watch time across productivity categories, plus % productive
SELECT
    watch_date,
    SUM(watch_minutes) FILTER (WHERE productivity_category = 'productive')    AS productive_minutes,
    SUM(watch_minutes) FILTER (WHERE productivity_category = 'neutral')       AS neutral_minutes,
    SUM(watch_minutes) FILTER (WHERE productivity_category = 'entertainment') AS entertainment_minutes,
    SUM(watch_minutes) AS total_minutes,
    ROUND(
        100.0 * SUM(watch_minutes) FILTER (WHERE productivity_category = 'productive')
        / NULLIF(SUM(watch_minutes), 0), 1
    ) AS productive_pct
FROM fact_watch_events
GROUP BY watch_date
ORDER BY watch_date;

-- name: weekday_trend
-- Total & average watch time by day of week (helps spot weekend binge patterns)
SELECT
    day_of_week,
    is_weekend,
    COUNT(*) AS event_count,
    SUM(watch_minutes) AS total_minutes,
    ROUND(AVG(watch_minutes), 2) AS avg_minutes_per_event
FROM fact_watch_events
GROUP BY day_of_week, is_weekend
ORDER BY
    CASE day_of_week
        WHEN 'Monday' THEN 1 WHEN 'Tuesday' THEN 2 WHEN 'Wednesday' THEN 3
        WHEN 'Thursday' THEN 4 WHEN 'Friday' THEN 5 WHEN 'Saturday' THEN 6
        WHEN 'Sunday' THEN 7
    END;

-- name: binge_sessions
-- Sessions (from transform.py's session_id) with 3+ videos -- i.e. binge-watching
SELECT
    session_id,
    MIN(watch_datetime) AS session_start,
    MAX(watch_datetime) AS session_end,
    COUNT(*) AS videos_watched,
    SUM(watch_minutes) AS total_minutes,
    STRING_AGG(DISTINCT productivity_category, ', ') AS categories_involved
FROM fact_watch_events
GROUP BY session_id
HAVING COUNT(*) >= 3
ORDER BY videos_watched DESC
LIMIT 20;

-- name: top_channels
-- Most-watched channels overall, with their productivity category
SELECT
    c.name AS channel_name,
    c.productivity_category,
    COUNT(*) AS watch_count,
    SUM(f.watch_minutes) AS total_minutes
FROM fact_watch_events f
JOIN dim_channel c ON c.channel_id = f.channel_id
GROUP BY c.name, c.productivity_category
ORDER BY watch_count DESC
LIMIT 15;

-- name: overall_summary
-- Single-row high-level summary across the whole loaded history
SELECT
    COUNT(*) AS total_events,
    COUNT(DISTINCT watch_date) AS days_covered,
    SUM(watch_minutes) AS total_minutes,
    ROUND(SUM(watch_minutes) / 60.0, 1) AS total_hours,
    ROUND(
        100.0 * SUM(watch_minutes) FILTER (WHERE productivity_category = 'productive')
        / NULLIF(SUM(watch_minutes), 0), 1
    ) AS overall_productive_pct;

-- name: api_coverage
-- Shows what percentage of loaded watch events have real API-sourced metadata
-- vs. keyword-based fallback. Useful for verifying enrichment quality.
SELECT
    api_enriched,
    COUNT(*) AS event_count,
    ROUND(100.0 * COUNT(*) / NULLIF(SUM(COUNT(*)) OVER (), 0), 1) AS pct,
    ROUND(AVG(watch_minutes), 2) AS avg_watch_minutes
FROM fact_watch_events
GROUP BY api_enriched
ORDER BY api_enriched DESC;

-- name: category_breakdown
-- Breakdown by YouTube's official video category (only for API-enriched rows)
SELECT
    youtube_category_name,
    productivity_category,
    COUNT(*) AS event_count,
    SUM(watch_minutes) AS total_minutes,
    ROUND(AVG(watch_minutes), 2) AS avg_minutes
FROM fact_watch_events
WHERE api_enriched = true AND youtube_category_name IS NOT NULL
GROUP BY youtube_category_name, productivity_category
ORDER BY total_minutes DESC;
