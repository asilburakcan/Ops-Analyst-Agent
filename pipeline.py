"""Daily job, triggered by cron on EC2. One command, no menu.

python pipeline.py            ingest (only if tables are missing) -> score today's packages -> analyst report
python pipeline.py --eval     ... plus the golden-set check of the SQL agent
python pipeline.py --refresh  re-ingest the source data first

Every run is saved to S3 / Glue (risk_flags, model_metrics, daily_reports) and can be queried in Athena.
"""
import json
import sys
import time

import pandas as pd

import agents
import backend as b
import eval as golden
import ingest
import model


def main(args):
    t0, ts = time.time(), pd.Timestamp.now().floor("s")
    if "--refresh" in args or not all(b.exists(t) for t in b.TABLES):
        print("ingest:", ingest.run())

    scan = model.run()
    report = agents.analyze("Daily failed-delivery risk scan of today's routes: what should operations do today?",
                            scan["summary"])
    report = {k: report.get(k, "") for k in ("finding", "root_cause_hypothesis", "automation_idea")}
    row = {"run_ts": ts, **scan["metrics"], **report}
    if "--eval" in args:
        row |= {f"agent_{k}": v for k, v in golden.run().items() if k in ("accuracy", "execution_rate")}
    row["runtime_s"] = round(time.time() - t0)
    b.save(pd.DataFrame([row]), "daily_reports")
    print(json.dumps(row, indent=2, default=str))


if __name__ == "__main__":
    main(sys.argv[1:])
