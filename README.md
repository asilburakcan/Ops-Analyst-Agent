# Ops Analyst Agent: Last Mile

Dispatchers check by hand which packages will fail at the door and answer operations questions by writing SQL. This project automates both on AWS, from data that already exists:

- **Failed-delivery risk model (LightGBM):** every day it scores the day's packages before the vans leave and saves the riskiest 1% for review.
- **SQL agent:** turns a question into Athena SQL and repairs its own failed queries.
- **Analyst agent:** turns a result into a finding, a root-cause hypothesis and an automation idea. It writes the daily report.

Each part is checked against ground truth. The model is tested on days it never saw. The SQL agent is scored on a 10-question golden set with reference SQL.

## Architecture

```
Amazon Last Mile open data (public S3, us-east-1)
        │  ingest.py: flatten nested JSON, check data, write Parquet
        ▼
Own S3 bucket (Parquet) ──► Glue Data Catalog ──► Athena ◄── SQL agent ──► Bedrock
        ▲                                           │
        └── risk_flags, model_metrics, daily_reports ◄── model.py + analyst agent (Bedrock)

EC2: cron runs `python pipeline.py` every day. Credentials come from the instance IAM role.
```

| File | Job |
|---|---|
| `backend.py` | The only file that talks to AWS: `query()` (Athena), `save()` (S3 + Glue), `llm()` (Bedrock) |
| `ingest.py` | Public S3 → `lm_routes`, `lm_stops`, `lm_packages` in own S3 + Glue, with data checks |
| `model.py` | Failed-delivery risk model, time-split validation, daily risk flags |
| `agents.py` | SQL agent (self-repair) and analyst agent |
| `eval.py` | Golden-set check of the SQL agent |
| `pipeline.py` | The single entry point that cron triggers |

## Data

[Amazon Last Mile Routing Research Challenge](https://registry.opendata.aws/amazon-last-mile-challenges/) (2021): 6,112 real routes from 17 stations in 5 US metro areas, July–August 2018. The project uses 3 files (465 MB) and skips `travel_times.json` (1.8 GB). The data is not in this repo: `ingest.py` reads it from the public bucket. It is licensed [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) by Amazon. The code is MIT licensed.

| Table | Rows | One row is |
|---|---|---|
| `lm_routes` | 6,112 | a route |
| `lm_stops` | 904,527 | a stop on a route |
| `lm_packages` | 1,457,175 | a package at a stop |

Data checks run on every ingest. The run stops if a package has no stop, a stop has no visit order or a row is duplicated. Two real data facts are reported, not removed:
- 6,515 dropoff stops have no `zone_id`.
- 1,432 packages appear at two stops of the same route: attempted at one, delivered at another.

## Results

Model results below come from a local test run on the same data. AWS run results will be added here.

**Risk model** (trained on 2018-07-19 → 08-13, tested on 356k packages from 08-14 → 08-26):

| | AUC |
|---|---|
| LightGBM | **0.80** |
| Past fail rate of the station | 0.59 |
| "Has a time window" rule | 0.58 |

- Failed deliveries are 0.62% of the test packages. In the flagged 1% they are **5.4%, 8.7× the average**.
- Packages with a delivery time window fail 4× more often (2.38% vs 0.62%), but they are only 7.8% of all packages.
- The strongest signal is planned service time at the stop, followed by packages per stop, station, time to the window deadline, and route size.

**SQL agent golden set:** _to fill after the first AWS run_

## Run on AWS

1. **IAM role for EC2** with `AmazonS3FullAccess`, `AmazonAthenaFullAccess`, `AWSGlueConsoleFullAccess` and `AmazonBedrockFullAccess`. Check in the Bedrock console that the Nova models are available in `eu-central-1`.
2. **EC2:** Amazon Linux 2023, `t3.small` in `eu-central-1` with the role attached. Ingest peaks at about 1.5 GB RAM, so add a 2 GB swap file. Open SSH to your own IP only.
3. **Install:**
   ```bash
   sudo dnf install -y git python3.11 python3.11-pip
   git clone https://github.com/<user>/ops-analyst-agent.git && cd ops-analyst-agent
   python3.11 -m venv venv && venv/bin/pip install -r requirements.txt
   cp .env.example .env   # set S3_BUCKET to a globally unique name
   venv/bin/python pipeline.py --eval   # first run also ingests
   ```
4. **Daily trigger:**
   ```bash
   mkdir -p logs && (crontab -l 2>/dev/null; echo "0 5 * * * cd $PWD && venv/bin/python pipeline.py >> logs/pipeline.log 2>&1") | crontab -
   ```
5. **See the output in Athena:**
   ```sql
   SELECT * FROM last_mile.daily_reports ORDER BY run_ts DESC LIMIT 5;
   ```

Ask the SQL agent a single question: `venv/bin/python agents.py "Which station has the highest failed delivery rate?"`

**Cost:** Downloads from the open-data bucket are free. The data in our S3 is 86 MB of Parquet (465 MB of JSON before) (cents per month). Athena charges $5 per TB scanned and Bedrock costs a few cents per run. Most of the cost is EC2 `t3.small` while it is running, about $0.024 per hour. Stop the instance when you don't need the daily run.

**Safety:** The agent may only run a single `SELECT`, and write keywords are blocked. Give the Athena workgroup a bytes-scanned limit per query. No access keys are stored on the server.
