"""
Stage 4: ANALYSIS / REPORT
Parses sql/analysis_queries.sql (each query prefixed with `-- name: <label>`),
runs each one against Postgres, and prints/saves a human-readable insights report.
"""
import logging
import re
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text
from tabulate import tabulate

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def parse_named_queries(sql_path: Path) -> dict:
    """Splits a .sql file into {name: query_text} based on `-- name: X` markers."""
    content = Path(sql_path).read_text()
    chunks = re.split(r"--\s*name:\s*(\w+)", content)
    # chunks alternates: [preamble, name1, query1, name2, query2, ...]
    queries = {}
    for i in range(1, len(chunks), 2):
        name = chunks[i].strip()
        query = chunks[i + 1].strip().rstrip(";")
        queries[name] = query
    return queries


def run_all_queries(sqlalchemy_uri: str, sql_path: Path) -> dict:
    queries = parse_named_queries(sql_path)
    engine = create_engine(sqlalchemy_uri)
    results = {}
    with engine.connect() as conn:
        for name, query in queries.items():
            try:
                results[name] = pd.read_sql(text(query), conn)
            except Exception as e:
                logger.error("Query '%s' failed: %s", name, e)
                results[name] = pd.DataFrame()
    engine.dispose()
    return results


def print_report(results: dict):
    print("\n" + "=" * 70)
    print("WATCHWISE -- PRODUCTIVITY & HABIT INSIGHTS REPORT")
    print("=" * 70)

    if "overall_summary" in results and not results["overall_summary"].empty:
        row = results["overall_summary"].iloc[0]
        print(f"\nTotal watch events   : {int(row['total_events'])}")
        print(f"Days covered         : {int(row['days_covered'])}")
        print(f"Total watch time     : {row['total_hours']} hours")
        print(f"Overall productive % : {row['overall_productive_pct']}%")

    if "peak_usage_hour" in results and not results["peak_usage_hour"].empty:
        top = results["peak_usage_hour"].iloc[0]
        print(f"\nPeak usage hour: {int(top['watch_hour'])}:00 "
              f"({int(top['event_count'])} videos watched at that hour)")
        print("\nTop 5 hours by activity:")
        print(tabulate(results["peak_usage_hour"].head(5), headers="keys",
                        tablefmt="simple", showindex=False))

    if "productivity_ratio" in results and not results["productivity_ratio"].empty:
        print("\nDaily productivity ratio (most recent 10 days):")
        print(tabulate(results["productivity_ratio"].tail(10), headers="keys",
                        tablefmt="simple", showindex=False))

    if "weekday_trend" in results and not results["weekday_trend"].empty:
        print("\nWatch time by day of week:")
        print(tabulate(results["weekday_trend"], headers="keys",
                        tablefmt="simple", showindex=False))

    if "binge_sessions" in results and not results["binge_sessions"].empty:
        print(f"\nTop binge-watching sessions (>= 3 videos back-to-back):")
        print(tabulate(results["binge_sessions"].head(10), headers="keys",
                        tablefmt="simple", showindex=False))

    if "top_channels" in results and not results["top_channels"].empty:
        print("\nTop channels by watch count:")
        print(tabulate(results["top_channels"], headers="keys",
                        tablefmt="simple", showindex=False))

    print("\n" + "=" * 70)


def save_report_csvs(results: dict, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, df in results.items():
        if not df.empty:
            df.to_csv(out_dir / f"{name}.csv", index=False)
    logger.info("Saved %d report CSVs to %s", len(results), out_dir)


def main():
    from config.config import Config

    results = run_all_queries(Config.sqlalchemy_uri(), Config.SQL_DIR / "analysis_queries.sql")
    print_report(results)
    save_report_csvs(results, Config.PROJECT_ROOT / "data" / "reports")


if __name__ == "__main__":
    main()

