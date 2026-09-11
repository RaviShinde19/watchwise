# YouTube Productivity Analyzer Pipeline

An end-to-end ETL pipeline that processes YouTube watch history data, enriches it
with real video metadata from the YouTube Data API v3 (durations, categories),
loads it into PostgreSQL, and surfaces productivity insights (peak usage hours,
productive vs. distracting time split, binge-watching sessions, weekday trends)
-- orchestrated with Apache Airflow.

## Architecture

```
Google Takeout JSON
        |
        v
 +---------------+      +------------------+      +-----------------+
 |   EXTRACT     | ---> |   ENRICH (API)   | ---> |   TRANSFORM     |
 | (raw watch    |      | (YouTube Data    |      | (clean, dedupe, |
 |  history)     |      |  API v3: real    |      |  categorize w/  |
 |               |      |  durations &     |      |  API categories,|
 |               |      |  categories)     |      |  enrich w/ time)|
 +---------------+      +------------------+      +--------+--------+
                                                            |
                                                            v
                         +-------------------+     +----------------+
                         |  ANALYSIS / SQL   | <-- |     LOAD       |
                         |  peak hours,      |     | (PostgreSQL:   |
                         |  productivity %,  |     |  star schema)  |
                         |  binge sessions   |     +----------------+
                         +--------+----------+
                                  |
                                  v
                         +-------------------+
                         |  SUGGESTIONS      |
                         |  rule-based       |
                         |  insight engine   |
                         +-------------------+
```

All six stages are wired together as an Airflow DAG (`dags/youtube_productivity_dag.py`),
but every stage also runs standalone via plain Python for local development/testing
(no Airflow required).

## Project structure

```
youtube_productivity_pipeline/
+-- README.md
+-- requirements.txt
+-- .env.example                  # DB + API key template
+-- config/
|   +-- config.py                 # central config (env-driven)
+-- data/
|   +-- watch-history.json        # Google Takeout export (your real data)
|   +-- video_cache.json          # cached YouTube API responses (auto-generated)
+-- src/
|   +-- generate_sample_data.py   # creates synthetic watch-history.json for testing
|   +-- etl/
|   |   +-- extract.py            # Stage 1: read raw export
|   |   +-- enrich.py             # Stage 2: YouTube Data API v3 enrichment
|   |   +-- transform.py          # Stage 3: clean + enrich with pandas
|   |   +-- load.py               # Stage 4: load into Postgres
|   |   +-- pipeline.py           # glue code to run all 6 stages locally
|   +-- analysis/
|       +-- report.py             # Stage 5: run SQL analysis, print/save insights
|       +-- suggestions.py        # Stage 6: rule-based suggestion engine
+-- sql/
|   +-- schema.sql                # DDL -- star schema + migration
|   +-- analysis_queries.sql      # all analytical queries used by report.py
+-- dags/
|   +-- youtube_productivity_dag.py  # Airflow DAG
+-- tests/
    +-- test_enrich.py            # enrichment module tests
    +-- test_transform.py         # transform tests
    +-- test_suggestions.py       # suggestion engine tests
```

## 1. Getting your real data

Google Takeout lets you export your actual YouTube watch history:
`takeout.google.com` -> select **YouTube and YouTube Music** -> export as **JSON** ->
you'll get a `watch-history.json` file. Drop it into `data/watch-history.json`.

Until you have that, `src/generate_sample_data.py` creates a realistic synthetic
version so you can run and test the whole pipeline immediately.

## 2. YouTube Data API v3 setup (optional but recommended)

The pipeline can optionally call the YouTube Data API to fetch **real video
durations and official categories** for every video in your watch history.
Without it, the pipeline falls back to keyword-based categorization and
estimated 6-minute durations.

### Getting an API key (free, 5 minutes):

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a project (any name)
3. Search "YouTube Data API v3" -> Enable it
4. Go to Credentials -> Create API Key
5. Copy the key into your `.env` file as `YOUTUBE_API_KEY=your_key`

**Quota**: You get 10,000 free units/day. Each API call fetches 50 videos
and costs 1 unit, so you can enrich **500,000 videos/day** for free.
A typical watch history of ~5,000 videos needs only ~100 API calls.

**Caching**: API responses are cached locally in `data/video_cache.json`.
Re-running the pipeline never re-fetches already-cached videos, so quota is
only consumed on the first run (or when new videos appear in your history).

## 3. Setup

```bash
cd youtube_productivity_pipeline
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # then edit .env with your Postgres credentials + API key
```

Create the database and schema:

```bash
createdb youtube_analytics
psql youtube_analytics -f sql/schema.sql
```

## 4. Run it locally (no Airflow)

```bash
# 1. generate sample data (skip if you have a real watch-history.json)
python src/generate_sample_data.py

# 2. run the full pipeline: extract -> enrich -> transform -> load -> analyze -> suggest
python -m src.etl.pipeline

# 3. (optional) re-print the insights report or suggestions on their own
python -m src.analysis.report
python -m src.analysis.suggestions
```

`src.etl.pipeline` runs every stage in order and prints both the analysis report
and the personalized suggestions at the end. On first run with an API key, you'll
see the enrichment step fetching real metadata (subsequent runs use the cache).

## 5. Run it with Airflow

```bash
export AIRFLOW_HOME=$(pwd)/airflow_home
airflow db init
airflow users create --username admin --password admin --firstname A --lastname D \
  --role Admin --email admin@example.com

# point Airflow at this project's dags/ folder
mkdir -p $AIRFLOW_HOME/dags
ln -s $(pwd)/dags/youtube_productivity_dag.py $AIRFLOW_HOME/dags/

airflow webserver -p 8080 &
airflow scheduler &
```

Open `http://localhost:8080`, un-pause `youtube_productivity_pipeline`, and trigger it.

## 6. What "productivity" means here

**With API key (recommended):** YouTube assigns every video an official category
(Education, Science & Technology, Entertainment, Gaming, Music, etc.). The pipeline
maps these to productivity buckets:

| YouTube Category | Mapped To |
|---|---|
| Education | productive |
| Science & Technology | productive |
| News & Politics | productive |
| Documentary | productive |
| Music, People & Blogs, Sports | neutral |
| Entertainment, Gaming, Comedy | entertainment |

**Without API key (fallback):** Every channel is bucketed via keyword rules in
`src/etl/transform.py`:

- **productive** -- tutorials, courses, tech talks, documentaries, news, coding
- **neutral** -- music, podcasts, vlogs
- **entertainment** -- gaming, comedy, shorts, memes, reactions

## 7. Key metrics produced

| Metric | Query | Description |
|---|---|---|
| Peak usage hour | `peak_usage_hour` | Hour-of-day (0-23) with most watch events |
| Productivity ratio | `productivity_ratio` | % of watch time in "productive" category, by day |
| Weekday trend | `weekday_trend` | Total watch time by day of week |
| Binge sessions | `binge_sessions` | Sequences of 3+ videos with <10 min gaps |
| Top channels | `top_channels` | Most-watched channels by total watch count |
| API coverage | `api_coverage` | % of events enriched via API vs keyword fallback |
| Category breakdown | `category_breakdown` | Watch time by YouTube's official categories |

All queries live in `sql/analysis_queries.sql` and are executed from
`src/analysis/report.py`.

## 8. Suggestion engine (rule-based insights)

`src/analysis/suggestions.py` reads the same query results from step 7 and
applies a set of independent, pure-function rules. Each rule either fires
(returns a suggestion) or stays silent -- there's no ML involved, so every
suggestion is fully explainable by the exact rule and numbers that triggered it.

| Rule | Fires when |
|---|---|
| `low_overall_productivity` | All-time productive-content share is below 25% |
| `late_night_peak_usage` | Peak usage hour falls in a late-night window (21:00-02:00) |
| `binge_session_detected` | A session has 5+ videos back-to-back |
| `weekend_activity_gap` | Weekend watch time is under 20% of total |
| `productivity_trend_declining` | Last-7-day avg productive % drops 10+ points vs. prior 7 days |

Suggestions are persisted to `insights_suggestions` (append-only, with a JSONB
`evidence` column recording the exact numbers behind each one) so you can track
how they change as more history accumulates.
