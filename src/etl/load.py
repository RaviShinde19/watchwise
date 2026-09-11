"""
Stage 3: LOAD
Loads the transformed DataFrame into PostgreSQL following the star schema defined
in sql/schema.sql:
  - dim_channel   : one row per unique channel
  - fact_watch_events : one row per watch event, FK'd to dim_channel

Uses upsert semantics (ON CONFLICT DO NOTHING / DO UPDATE) so the pipeline is safe
to re-run without creating duplicates.
"""
import logging

import pandas as pd
from sqlalchemy import create_engine, text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_engine(sqlalchemy_uri: str):
    return create_engine(sqlalchemy_uri)


def load_dim_channel(df: pd.DataFrame, engine) -> pd.DataFrame:
    """
    Upserts unique channels into dim_channel and returns a mapping DataFrame of
    channel_name -> channel_id so fact rows can be linked by foreign key.
    """
    channels = (
        df[["channel_name", "channel_url"]]
        .drop_duplicates(subset=["channel_name"])
        .rename(columns={"channel_name": "name", "channel_url": "url"})
    )

    # Get youtube category info if available (from enrichment)
    channel_categories = {}
    if "youtube_category_id" in df.columns:
        for _, row in df.dropna(subset=["youtube_category_id"]).drop_duplicates(
            subset=["channel_name"]
        ).iterrows():
            channel_categories[row["channel_name"]] = {
                "youtube_category_id": row["youtube_category_id"],
                "youtube_category_name": row["youtube_category_name"],
            }

    with engine.begin() as conn:
        for _, row in channels.iterrows():
            cat_info = channel_categories.get(row["name"], {})
            conn.execute(
                text(
                    """
                    INSERT INTO dim_channel (name, url, productivity_category,
                                            youtube_category_id, youtube_category_name)
                    VALUES (:name, :url, :category, :yt_cat_id, :yt_cat_name)
                    ON CONFLICT (name) DO UPDATE
                        SET url = EXCLUDED.url,
                            youtube_category_id = COALESCE(EXCLUDED.youtube_category_id, dim_channel.youtube_category_id),
                            youtube_category_name = COALESCE(EXCLUDED.youtube_category_name, dim_channel.youtube_category_name)
                    """
                ),
                {
                    "name": row["name"],
                    "url": row["url"],
                    "category": df.loc[
                        df["channel_name"] == row["name"], "productivity_category"
                    ].iloc[0],
                    "yt_cat_id": cat_info.get("youtube_category_id"),
                    "yt_cat_name": cat_info.get("youtube_category_name"),
                },
            )

        channel_map = pd.read_sql("SELECT channel_id, name FROM dim_channel", conn)

    logger.info("Upserted %d channels into dim_channel", len(channels))
    return channel_map


def load_fact_watch_events(df: pd.DataFrame, channel_map: pd.DataFrame, engine):
    merged = df.merge(
        channel_map, left_on="channel_name", right_on="name", how="left"
    )

    fact_cols = merged[
        [
            "channel_id", "video_title", "video_url", "watch_datetime",
            "watch_date", "watch_hour", "day_of_week", "is_weekend",
            "productivity_category", "session_id", "watch_minutes",
            "api_enriched", "youtube_category_id", "youtube_category_name",
        ]
    ].copy()

    with engine.begin() as conn:
        # Stage into a temp table, then upsert -- avoids row-by-row INSERTs for speed
        fact_cols.to_sql("fact_watch_events_staging", conn, if_exists="replace", index=False)
        conn.execute(
            text(
                """
                INSERT INTO fact_watch_events (
                    channel_id, video_title, video_url, watch_datetime,
                    watch_date, watch_hour, day_of_week, is_weekend,
                    productivity_category, session_id, watch_minutes,
                    api_enriched, youtube_category_id, youtube_category_name
                )
                SELECT
                    channel_id, video_title, video_url, watch_datetime,
                    watch_date, watch_hour, day_of_week, is_weekend,
                    productivity_category, session_id, watch_minutes,
                    api_enriched, youtube_category_id, youtube_category_name
                FROM fact_watch_events_staging
                ON CONFLICT (video_url, watch_datetime) DO NOTHING
                """
            )
        )
        conn.execute(text("DROP TABLE fact_watch_events_staging"))

    logger.info("Loaded %d watch events into fact_watch_events", len(fact_cols))


def load(df: pd.DataFrame, sqlalchemy_uri: str):
    engine = get_engine(sqlalchemy_uri)
    channel_map = load_dim_channel(df, engine)
    load_fact_watch_events(df, channel_map, engine)
    engine.dispose()


if __name__ == "__main__":
    from config.config import Config
    from src.etl.extract import extract_raw_history
    from src.etl.transform import transform

    raw_df = extract_raw_history(Config.RAW_DATA_PATH)
    clean_df = transform(raw_df)
    load(clean_df, Config.sqlalchemy_uri())
    print("Load complete.")
