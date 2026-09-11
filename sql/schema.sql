-- ============================================================================
-- YouTube Productivity Analyzer -- PostgreSQL schema
-- Run with: psql youtube_analytics -f sql/schema.sql
-- ============================================================================

-- Dimension table: one row per unique channel
CREATE TABLE IF NOT EXISTS dim_channel (
    channel_id              SERIAL PRIMARY KEY,
    name                    TEXT NOT NULL UNIQUE,
    url                     TEXT,
    productivity_category   TEXT NOT NULL DEFAULT 'unknown'
        CHECK (productivity_category IN ('productive', 'neutral', 'entertainment', 'unknown')),
    youtube_category_id     TEXT,
    youtube_category_name   TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Fact table: one row per watch event
CREATE TABLE IF NOT EXISTS fact_watch_events (
    event_id                BIGSERIAL PRIMARY KEY,
    channel_id              INTEGER NOT NULL REFERENCES dim_channel(channel_id),
    video_title             TEXT,
    video_url               TEXT NOT NULL,
    watch_datetime          TIMESTAMPTZ NOT NULL,
    watch_date              DATE NOT NULL,
    watch_hour              SMALLINT NOT NULL CHECK (watch_hour BETWEEN 0 AND 23),
    day_of_week             TEXT NOT NULL,
    is_weekend              BOOLEAN NOT NULL,
    productivity_category   TEXT NOT NULL
        CHECK (productivity_category IN ('productive', 'neutral', 'entertainment', 'unknown')),
    session_id              INTEGER NOT NULL,
    watch_minutes           NUMERIC NOT NULL DEFAULT 0,
    api_enriched            BOOLEAN NOT NULL DEFAULT false,
    youtube_category_id     TEXT,
    youtube_category_name   TEXT,
    loaded_at               TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Prevents duplicate loads of the same video watched at the same instant
    CONSTRAINT uq_video_watch UNIQUE (video_url, watch_datetime)
);

-- Indexes to speed up the analytical queries in analysis_queries.sql
CREATE INDEX IF NOT EXISTS idx_fact_watch_date       ON fact_watch_events (watch_date);
CREATE INDEX IF NOT EXISTS idx_fact_watch_hour       ON fact_watch_events (watch_hour);
CREATE INDEX IF NOT EXISTS idx_fact_channel_id       ON fact_watch_events (channel_id);
CREATE INDEX IF NOT EXISTS idx_fact_session_id       ON fact_watch_events (session_id);
CREATE INDEX IF NOT EXISTS idx_fact_prod_category    ON fact_watch_events (productivity_category);
CREATE INDEX IF NOT EXISTS idx_fact_api_enriched     ON fact_watch_events (api_enriched);

-- Convenience view joining fact + dim for ad-hoc querying
CREATE OR REPLACE VIEW vw_watch_events AS
SELECT
    f.event_id,
    f.video_title,
    f.video_url,
    c.name AS channel_name,
    f.watch_datetime,
    f.watch_date,
    f.watch_hour,
    f.day_of_week,
    f.is_weekend,
    f.productivity_category,
    f.session_id,
    f.watch_minutes,
    f.api_enriched,
    f.youtube_category_id,
    f.youtube_category_name
FROM fact_watch_events f
JOIN dim_channel c ON c.channel_id = f.channel_id;

-- ============================================================================
-- Suggestion engine output: one row per rule-triggered suggestion, per run.
-- Populated by src/analysis/suggestions.py (Stage 5). Kept historically (not
-- overwritten) so you can see how suggestions evolve as more data comes in.
-- ============================================================================
CREATE TABLE IF NOT EXISTS insights_suggestions (
    suggestion_id   BIGSERIAL PRIMARY KEY,
    generated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    rule_name       TEXT NOT NULL,
    severity        TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    message         TEXT NOT NULL,
    evidence        JSONB
);

CREATE INDEX IF NOT EXISTS idx_suggestions_generated_at ON insights_suggestions (generated_at);
CREATE INDEX IF NOT EXISTS idx_suggestions_rule_name    ON insights_suggestions (rule_name);

-- ============================================================================
-- Migration: run these if upgrading from the old schema (safe to re-run)
-- ============================================================================
DO $$
BEGIN
    -- Add new columns to dim_channel
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'dim_channel' AND column_name = 'youtube_category_id') THEN
        ALTER TABLE dim_channel ADD COLUMN youtube_category_id TEXT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'dim_channel' AND column_name = 'youtube_category_name') THEN
        ALTER TABLE dim_channel ADD COLUMN youtube_category_name TEXT;
    END IF;

    -- Add new columns to fact_watch_events
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'fact_watch_events' AND column_name = 'api_enriched') THEN
        ALTER TABLE fact_watch_events ADD COLUMN api_enriched BOOLEAN NOT NULL DEFAULT false;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'fact_watch_events' AND column_name = 'youtube_category_id') THEN
        ALTER TABLE fact_watch_events ADD COLUMN youtube_category_id TEXT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'fact_watch_events' AND column_name = 'youtube_category_name') THEN
        ALTER TABLE fact_watch_events ADD COLUMN youtube_category_name TEXT;
    END IF;

    -- Rename old column if it exists
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name = 'fact_watch_events' AND column_name = 'estimated_watch_minutes')
       AND NOT EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name = 'fact_watch_events' AND column_name = 'watch_minutes') THEN
        ALTER TABLE fact_watch_events RENAME COLUMN estimated_watch_minutes TO watch_minutes;
    END IF;
END
$$;
