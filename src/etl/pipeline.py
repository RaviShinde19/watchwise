"""
Runs the full pipeline (extract -> enrich -> transform -> load -> analyze -> suggest)
as a plain Python script, for local development and testing without needing Airflow
running. This is the exact same logic that dags/youtube_productivity_dag.py
calls -- the DAG just wraps these same functions as Airflow tasks.
"""
import logging

from config.config import Config
from src.etl.extract import extract_raw_history
from src.etl.enrich import enrich
from src.etl.load import load
from src.etl.transform import transform

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_pipeline():
    logger.info("=== Stage 1: EXTRACT ===")
    raw_df = extract_raw_history(Config.RAW_DATA_PATH)

    logger.info("=== Stage 2: ENRICH (YouTube API) ===")
    enriched_df = enrich(raw_df, Config.YOUTUBE_API_KEY, Config.VIDEO_CACHE_PATH)

    logger.info("=== Stage 3: TRANSFORM ===")
    clean_df = transform(enriched_df)
    clean_df.to_csv(Config.STAGED_DATA_PATH, index=False)
    logger.info("Staged cleaned data written to %s", Config.STAGED_DATA_PATH)

    logger.info("=== Stage 4: LOAD ===")
    load(clean_df, Config.sqlalchemy_uri())

    logger.info("=== Stage 5: ANALYZE ===")
    from src.analysis.report import run_all_queries, print_report, save_report_csvs
    results = run_all_queries(Config.sqlalchemy_uri(), Config.SQL_DIR / "analysis_queries.sql")
    print_report(results)
    save_report_csvs(results, Config.PROJECT_ROOT / "data" / "reports")

    logger.info("=== Stage 6: SUGGEST ===")
    from sqlalchemy import create_engine
    from src.analysis.suggestions import generate_suggestions, print_suggestions, save_suggestions

    suggestions = generate_suggestions(results)
    print_suggestions(suggestions)
    engine = create_engine(Config.sqlalchemy_uri())
    save_suggestions(suggestions, engine)
    engine.dispose()

    api_pct = 100 * clean_df["api_enriched"].sum() / max(len(clean_df), 1)
    logger.info(
        "Pipeline finished successfully. %d events processed, %d suggestions generated. "
        "API enrichment: %.1f%%",
        len(clean_df), len(suggestions), api_pct,
    )
    return len(clean_df)


if __name__ == "__main__":
    run_pipeline()
