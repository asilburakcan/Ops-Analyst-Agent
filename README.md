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
Own S3 bucket (Parquet) ──► Glue Data Catalog ──► Athena ◄── SQL agent ──► LLM (Groq or Bedrock)
        ▲                                           │
        └── risk_flags, model_metrics, daily_reports ◄── model.py + analyst agent

GitHub push ──► CodePipeline: Source ──► CodeBuild (compile + import check) ──► CodeDeploy ──► EC2
EC2: cron runs `python pipeline.py` every day at 05:00 UTC. Credentials come from the instance IAM role.
```

| File | Job |
|---|---|
| `backend.py` | The only file that talks to AWS: `query()` (Athena), `save()` (S3 + Glue), `llm()` (Groq, or Bedrock with `LLM=bedrock`) |
| `ingest.py` | Public S3 → `lm_routes`, `lm_stops`, `lm_packages` in own S3 + Glue, with data checks |
| `model.py` | Failed-delivery risk model, time-split validation, daily risk flags |
| `agents.py` | SQL agent (self-repair) and analyst agent, both grounded in the glossary of `DATA_DICTIONARY.md` |
| `DATA_DICTIONARY.md` | Terms, tables and columns; its glossary is loaded into both agents' prompts |
| `eval.py` | Golden-set check of the SQL agent |
| `pipeline.py` | The single entry point that cron triggers |
| `app.py` | Streamlit operator view: today's report, risk flags by station, and a question box for the agents |
| `buildspec.yml`, `appspec.yml`, `scripts/deploy.sh` | CI/CD: build check, deploy to EC2, install packages and the daily cron job |

## Data

[Amazon Last Mile Routing Research Challenge](https://registry.opendata.aws/amazon-last-mile-challenges/) (2021): 6,112 real routes from 17 stations in 5 US metro areas, July–August 2018. The project uses 3 files (465 MB) and skips `travel_times.json` (1.8 GB). The data is not in this repo: `ingest.py` reads it from the public bucket. It is licensed [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) by Amazon. The code is MIT licensed.

| Table | Rows | One row is |
|---|---|---|
| `lm_routes` | 6,112 | a route |
| `lm_stops` | 904,527 | a stop on a route |
| `lm_packages` | 1,457,175 | a package at a stop |

Every column and term is described in [DATA_DICTIONARY.md](DATA_DICTIONARY.md).

Data checks run on every ingest. The run stops if a package has no stop, a stop has no visit order or a row is duplicated. Two real data facts are reported, not removed:
- 6,515 dropoff stops have no `zone_id`.
- 1,432 packages appear at two stops of the same route: attempted at one, delivered at another.

## Results

First full AWS run (us-east-2, 2026-10-23): ingest → S3/Glue, model via Athena, analyst report and golden set. Total runtime 409 s; everything below is queryable in Athena.

**Risk model** (trained on 2018-07-19 → 08-13, tested on 356k packages from 08-14 → 08-26):

| | AUC |
|---|---|
| LightGBM | **0.80** |
| Past fail rate of the station | 0.59 |
| "Has a time window" rule | 0.58 |

- Failed deliveries are 0.62% of the test packages. In the flagged 1% (3,560 packages) they are **5.3%, 8.6× the average**.
- Accuracy is not used: with 0.62% failures, "everything gets delivered" already scores 99.38%.
- Packages with a delivery time window fail 4× more often (2.38% vs 0.62%), but they are only 7.8% of all packages.
- The strongest signal is planned service time at the stop, followed by packages per stop, station, time to the window deadline, and route size.

**SQL agent golden set: 11 / 11 correct, 0 repairs needed** (`openai/gpt-oss-120b` via Groq, SQL run on Athena). Questions cover joins, grouping, NULL handling, percentages and plain business wording ("station" → `station_code`). An empty result counts as a failure, so the agent repairs wrong filters too.

**Daily report written by the analyst agent:**
> *Finding:* Overall fail rate 0.62%; flagged 3560 packages (5.34% fail). Lift 8.6. Top risk stations: DLA8, DLA9, DLA7, DSE4, DCH1.
> *Automation idea:* Automated rerouting for flagged packages at high-risk stations based on service time and load.

**LLM provider:** Groq (`gpt-oss-120b` for SQL, `gpt-oss-20b` for the analyst) is the default. `LLM=bedrock` in `.env` runs the same agents on Amazon Bedrock (Nova) with no other code change. New AWS accounts can start with Bedrock quotas at 0, so Groq kept the project unblocked.

## Run on AWS

**Deployed setup (us-east-2):**
- **EC2** `t3.small`, Amazon Linux 2023, 2 GB swap. No SSH key, no open inbound port: access is through Systems Manager Session Manager.
- **IAM instance role** with S3, Athena, Glue and `AmazonSSMManagedInstanceCore`. No access keys on the server; the Groq key sits in a `chmod 600` `.env` that deploys never overwrite.
- **CI/CD:** every push to `main` runs CodePipeline. CodeBuild compiles the code and imports every module; a failure stops the deploy. CodeDeploy copies the code to EC2 and `scripts/deploy.sh` updates packages and the cron job.
- **Operator view:** `app.py` runs as a systemd service on `127.0.0.1:8501`. Open it with SSM port forwarding (`aws ssm start-session --document-name AWS-StartPortForwardingSession ...`); every question is saved to `agent_questions`.
- **Daily run:** cron starts `pipeline.py` at 05:00 UTC. Results land in S3 and are queryable in Athena:
  ```sql
  SELECT run_ts, auc, lift, agent_accuracy, finding FROM last_mile.daily_reports ORDER BY run_ts DESC LIMIT 5;
  ```

**Set it up yourself:**
1. IAM role for EC2: `AmazonS3FullAccess`, `AmazonAthenaFullAccess`, `AWSGlueConsoleFullAccess`, `AmazonSSMManagedInstanceCore` (add `AmazonBedrockFullAccess` only for `LLM=bedrock`).
2. EC2 with that role, 20 GiB disk. Install `git python3.11 cronie`, a 2 GB swap file and the CodeDeploy agent.
3. On the server: clone the repo, create `venv`, write `.env` from `.env.example`, run `venv/bin/python pipeline.py --eval` once (it also ingests).
4. CodeDeploy application + deployment group (EC2 tag `Name`), then a CodePipeline: GitHub source → CodeBuild (`buildspec.yml`) → CodeDeploy.

**About the data:** the dataset is historical (July–August 2018), so each daily run scores the same held-out days. The pipeline is built for live data: only the ingest source would change.

Ask the SQL agent a single question: `venv/bin/python agents.py "Which station has the highest failed delivery rate?"`

**Cost:** Downloads from the open-data bucket are free. The data in our S3 is 124 MB (Parquet tables, results and Athena output; the source JSON is 465 MB), a few cents per month. Athena charges $5 per TB scanned and an LLM run costs a few cents. Most of the cost is EC2 `t3.small` while it is running (about $0.024 per hour, ~$17/month). CodeBuild and CodeDeploy cost cents or nothing at this volume. Stop the instance when you don't need the daily run.

**Safety:** The agent may only run a single `SELECT`, and write keywords are blocked. Give the Athena workgroup a bytes-scanned limit per query. No access keys are stored on the server and no inbound port is open.
