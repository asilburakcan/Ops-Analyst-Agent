"""Golden-set check of the SQL agent: 10 questions, each with a reference SQL (the ground truth).

python eval.py  -> run all questions, save agent_results + agent_metrics
"""
import time
import uuid

import pandas as pd

import agents
import backend as b

FAILED = "CASE WHEN scan_status <> 'DELIVERED' THEN 1.0 ELSE 0 END"
GOLDEN = [
    ("What percentage of packages were not delivered (scan_status not DELIVERED)?",
     f"SELECT 100.0*avg({FAILED}) FROM lm_packages"),
    ("Number of packages per scan_status.",
     "SELECT scan_status, count(*) FROM lm_packages GROUP BY 1"),
    ("Number of routes per route_score.",
     "SELECT route_score, count(*) FROM lm_routes GROUP BY 1"),
    ("Failed delivery percentage per station_code.",
     f"SELECT r.station_code, 100.0*avg({FAILED}) FROM lm_packages p JOIN lm_routes r ON p.route_id = r.route_id GROUP BY 1"),
    ("Failed delivery percentage by has_time_window (true / false).",
     f"SELECT has_time_window, 100.0*avg({FAILED}) FROM lm_packages GROUP BY 1"),
    ("What percentage of packages have a delivery time window?",
     "SELECT 100.0*avg(CASE WHEN has_time_window THEN 1.0 ELSE 0 END) FROM lm_packages"),
    ("Average number of stops per route, per route_score.",
     "SELECT route_score, avg(n_stops) FROM lm_routes GROUP BY 1"),
    ("Top 5 station_code by average packages per route.",
     "SELECT station_code, avg(n_packages) FROM lm_routes GROUP BY 1 ORDER BY 2 DESC LIMIT 5"),
    ("Average planned_service_time_seconds of packages per station_code.",
     "SELECT r.station_code, avg(p.planned_service_time_seconds) FROM lm_packages p "
     "JOIN lm_routes r ON p.route_id = r.route_id GROUP BY 1"),
    ("How many Dropoff stops have no zone_id?",
     "SELECT count(*) FROM lm_stops WHERE type = 'Dropoff' AND zone_id IS NULL"),
]


def cell(v):
    try:
        return str(round(float(v), 2))
    except (TypeError, ValueError):
        return str(v).strip().lower()


def same(ref, got):
    """Is every column of the reference result in the agent result (any order, any column name)?"""
    if got is None or len(ref) != len(got):
        return False
    got_cols = [sorted(map(cell, got.iloc[:, i])) for i in range(got.shape[1])]
    return all(sorted(map(cell, ref.iloc[:, i])) in got_cols for i in range(ref.shape[1]))


def run():
    run_id, run_ts = uuid.uuid4().hex[:8], pd.Timestamp.now().floor("s")
    rows = []
    for q, ref in GOLDEN:
        sql, df, repairs = agents.write_sql(q)
        ok = int(same(b.query(ref), df))
        rows.append({"run_id": run_id, "run_ts": run_ts, "question": q, "generated_sql": sql,
                     "executed": int(df is not None), "repairs": repairs, "correct": ok})
        print(f"  {'CORRECT' if ok else 'WRONG  '} | repairs={repairs} | {q[:60]}")
        time.sleep(b.LLM_PAUSE)

    out = pd.DataFrame(rows)
    metrics = pd.DataFrame([{"run_id": run_id, "run_ts": run_ts, "questions": len(out),
                             "execution_rate": round(out.executed.mean(), 3), "accuracy": round(out.correct.mean(), 3),
                             "avg_repairs": round(out.repairs.mean(), 2),
                             "llm": b.LLM, "sql_model": b.SQL_MODEL, "analyst_model": b.ANALYST_MODEL}])
    b.save(out, "agent_results")
    b.save(metrics, "agent_metrics")
    return metrics.iloc[0].to_dict()


if __name__ == "__main__":
    print(run())
