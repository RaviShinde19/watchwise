"""
Airflow DAG: watchwise_pipeline (WatchWise)

Orchestrates the full pipeline daily:
    extract >> enrich >> transform >> load >> analyze >> suggest

Each task calls straight into the same src/etl/* and src/analysis/* functions used
for local runs (src/etl/pipeline.py) -- Airflow is purely an orchestration layer
here, not a place where business logic lives.

To install: symlink or copy this file into $AIRFLOW_HOME/dags/, and make sure the
project root is on PYTHONPATH (Airflow needs to import config, import src...).
"""
from pathlib import Path
import sys

# Add the project root inside the Docker container to Python's search path
PROJECT_ROOT = Path("/opt/airflow/project")
sys.path.insert(0, str(PROJECT_ROOT))

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

default_args = {
    "owner": "watchwise",
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": False,
}


def _extract(**context):
    from config.config import Config
    from src.etl.extract import extract_raw_history

    df = extract_raw_history(Config.RAW_DATA_PATH)
    # Push the raw row count to XCom for visibility in the Airflow UI
    context["ti"].xcom_push(key="raw_row_count", value=len(df))
    # Persist to a temp location so the next task can re-read it (Airflow tasks
    # may run on different workers, so we don't pass DataFrames via XCom)
    df.to_pickle("/tmp/yt_pipeline_raw.pkl")


def _enrich(**context):
    import pandas as pd

    from config.config import Config
    from src.etl.enrich import enrich

    raw_df = pd.read_pickle("/tmp/yt_pipeline_raw.pkl")
    enriched_df = enrich(raw_df, Config.YOUTUBE_API_KEY, Config.VIDEO_CACHE_PATH)
    enriched_df.to_pickle("/tmp/yt_pipeline_enriched.pkl")

    api_count = int(enriched_df["api_enriched"].sum())
    context["ti"].xcom_push(key="api_enriched_count", value=api_count)
    context["ti"].xcom_push(key="total_count", value=len(enriched_df))


def _transform(**context):
    import pandas as pd

    from config.config import Config
    from src.etl.transform import transform

    enriched_df = pd.read_pickle("/tmp/yt_pipeline_enriched.pkl")
    clean_df = transform(enriched_df)
    clean_df.to_csv(Config.STAGED_DATA_PATH, index=False)
    clean_df.to_pickle("/tmp/yt_pipeline_clean.pkl")
    context["ti"].xcom_push(key="clean_row_count", value=len(clean_df))


def _load(**context):
    import pandas as pd

    from config.config import Config
    from src.etl.load import load

    clean_df = pd.read_pickle("/tmp/yt_pipeline_clean.pkl")
    load(clean_df, Config.sqlalchemy_uri())


def _analyze(**context):
    from config.config import Config
    from src.analysis.report import run_all_queries, print_report, save_report_csvs

    results = run_all_queries(Config.sqlalchemy_uri(), Config.SQL_DIR / "analysis_queries.sql")
    print_report(results)  # shows up in the Airflow task log
    save_report_csvs(results, Config.PROJECT_ROOT / "data" / "reports")

    # Hand results to the next task via a pickle (same pattern as extract/transform)
    import pickle
    with open("/tmp/yt_pipeline_results.pkl", "wb") as f:
        pickle.dump(results, f)


def _suggest(**context):
    import pickle

    from config.config import Config
    from src.analysis.suggestions import generate_suggestions, print_suggestions, save_suggestions
    from sqlalchemy import create_engine

    with open("/tmp/yt_pipeline_results.pkl", "rb") as f:
        results = pickle.load(f)

    suggestions = generate_suggestions(results)
    print_suggestions(suggestions)  # shows up in the Airflow task log

    engine = create_engine(Config.sqlalchemy_uri())
    save_suggestions(suggestions, engine)
    engine.dispose()

    context["ti"].xcom_push(key="suggestion_count", value=len(suggestions))


with DAG(
    dag_id="watchwise_pipeline",
    description="ETL + API enrichment + analysis pipeline for YouTube watch history productivity insights",
    default_args=default_args,
    start_date=datetime(2024, 1, 1),
    schedule_interval="@daily",
    catchup=False,
    tags=["watchwise", "youtube", "etl", "productivity", "api"],
) as dag:

    extract_task = PythonOperator(
        task_id="extract_watch_history",
        python_callable=_extract,
    )

    enrich_task = PythonOperator(
        task_id="enrich_via_youtube_api",
        python_callable=_enrich,
    )

    transform_task = PythonOperator(
        task_id="transform_watch_history",
        python_callable=_transform,
    )

    load_task = PythonOperator(
        task_id="load_to_postgres",
        python_callable=_load,
    )

    analyze_task = PythonOperator(
        task_id="run_analysis_report",
        python_callable=_analyze,
    )

    suggest_task = PythonOperator(
        task_id="generate_suggestions",
        python_callable=_suggest,
    )

    extract_task >> enrich_task >> transform_task >> load_task >> analyze_task >> suggest_task
