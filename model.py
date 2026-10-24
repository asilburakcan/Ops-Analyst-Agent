"""Failed-delivery risk model (LightGBM): which packages will NOT be delivered on the first try?

- Target: scan_status <> 'DELIVERED' (DELIVERY_ATTEMPTED or REJECTED), about 0.8% of packages.
- Features are known before the van leaves; scan_status, visit_order and route_score are never used.
- Time split: routes of the newest 20% of days act as "today's routes". The model never sees them,
  but the data holds their real outcome, so every flag is checked against ground truth.

python model.py  -> train, score today's routes, save risk_flags + model_metrics
"""
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.metrics import roc_auc_score

import backend as b

FEATS = ["station_code", "dep_hour", "dow", "n_stops", "route_packages", "load_ratio",
         "stop_packages", "has_time_window", "deadline_h", "planned_service_time_seconds", "volume_cm3"]
TOP = 0.01  # operators review the riskiest 1% of today's packages

SQL = """
SELECT p.route_id, p.stop_id, p.package_id, p.scan_status, p.tw_end, p.has_time_window,
       p.planned_service_time_seconds, p.volume_cm3, s.n_packages AS stop_packages,
       r.station_code, r.route_date, r.departure_ts, r.n_stops, r.n_packages AS route_packages,
       r.total_volume_cm3, r.executor_capacity_cm3
FROM lm_packages p
JOIN lm_stops s ON s.route_id = p.route_id AND s.stop_id = p.stop_id
JOIN lm_routes r ON r.route_id = p.route_id"""


def features(df):
    df["route_date"], df["departure_ts"] = pd.to_datetime(df.route_date), pd.to_datetime(df.departure_ts)
    df["dep_hour"], df["dow"] = df.departure_ts.dt.hour, df.route_date.dt.dayofweek
    df["load_ratio"] = df.total_volume_cm3 / df.executor_capacity_cm3
    df["deadline_h"] = (pd.to_datetime(df.tw_end) - df.departure_ts).dt.total_seconds() / 3600  # NaN: no window
    df["has_time_window"] = df.has_time_window.astype(int)
    df["station_code"] = df.station_code.astype("category")
    df["failed"] = (df.scan_status != "DELIVERED").astype(int)
    return df


def comparisons(te, flagged):
    """Fixed, tested comparisons on today's packages, so the analyst's root cause rests on data, not guesses."""
    te = te.assign(group=flagged.map({True: "flagged", False: "not flagged"}))
    pct = lambda s: round(100 * s.mean(), 2)  # noqa: E731
    by_flag = te.groupby("group").agg(
        packages=("failed", "size"), fail_rate_pct=("failed", pct), time_window_share_pct=("has_time_window", pct),
        avg_service_time_s=("planned_service_time_seconds", "mean"), avg_packages_at_stop=("stop_packages", "mean"),
        avg_load_ratio=("load_ratio", "mean")).round(2)
    by_window = te.groupby("has_time_window").agg(packages=("failed", "size"), fail_rate_pct=("failed", pct))
    service_band = pd.qcut(te.planned_service_time_seconds, 4, labels=["shortest 25%", "short", "long", "longest 25%"],
                           duplicates="drop")
    by_service = te.groupby(service_band, observed=True).agg(packages=("failed", "size"), fail_rate_pct=("failed", pct))
    by_station = (te.groupby("station_code", observed=True)
                  .agg(flagged=("group", lambda g: int((g == "flagged").sum())), fail_rate_pct=("failed", pct))
                  .sort_values("flagged", ascending=False).head(5))
    return {"flagged_vs_not_flagged": by_flag.to_dict("index"),
            "fail_rate_by_time_window": {("with window" if k else "no window"): v
                                         for k, v in by_window.to_dict("index").items()},
            "fail_rate_by_planned_service_time": by_service.to_dict("index"),
            "top_flagged_stations_today": by_station.to_dict("index")}


def run(df=None, save=True):
    df = features(b.query(SQL, big=True) if df is None else df)
    cut = df.route_date.quantile(0.8)
    tr, te = df[df.route_date < cut], df[df.route_date >= cut].copy()

    model = LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=31, min_child_samples=200,
                           importance_type="gain", random_state=42, verbose=-1)
    model.fit(tr[FEATS], tr.failed)
    te["risk"] = model.predict_proba(te[FEATS])[:, 1].round(4)

    y, flagged = te.failed, te.risk >= te.risk.quantile(1 - TOP)
    station_rate = te.station_code.map(tr.groupby("station_code", observed=True).failed.mean()).astype(float)
    metrics = {
        "train_packages": len(tr), "today_packages": len(te), "today_from": str(cut.date()),
        "fail_rate": round(y.mean(), 4),
        "auc": round(roc_auc_score(y, te.risk), 3),
        "auc_station_baseline": round(roc_auc_score(y, station_rate), 3),  # "past fail rate of the station"
        "auc_time_window_baseline": round(roc_auc_score(y, te.has_time_window), 3),
        "flagged": int(flagged.sum()),
        "fail_rate_flagged": round(y[flagged].mean(), 4),
        "fail_rate_not_flagged": round(y[~flagged].mean(), 4),
        "failures_caught": round(y[flagged].sum() / y.sum(), 3),
    }
    metrics["lift"] = round(metrics["fail_rate_flagged"] / metrics["fail_rate"], 1)
    importance = pd.Series(model.feature_importances_, FEATS).sort_values(ascending=False)

    flags = te[flagged].sort_values("risk", ascending=False)[
        ["route_id", "stop_id", "package_id", "station_code", "route_date", "risk", "failed"]]
    flags = flags.rename(columns={"failed": "actual_failed"}).astype({"station_code": str})
    if save:
        ts = pd.Timestamp.now(tz="UTC").tz_localize(None).floor("s")
        b.save(flags.assign(scan_ts=ts), "risk_flags")
        b.save(pd.DataFrame([{"scan_ts": ts, **metrics}]), "model_metrics")

    summary = {"metrics": metrics,
               "top_features": (importance / importance.sum()).round(3).head(5).to_dict(),
               "comparisons": comparisons(te, flagged)}
    return {"metrics": metrics, "summary": summary, "flags": flags}


if __name__ == "__main__":
    r = run()
    print(pd.Series(r["metrics"]).to_string(), "\n", r["summary"]["top_features"])
