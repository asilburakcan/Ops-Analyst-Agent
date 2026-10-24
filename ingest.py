"""Ingest: Amazon Last Mile Routing open data (public S3) -> flat Parquet tables in our S3 + Glue.

python ingest.py   (pipeline.py runs it automatically when the tables are missing)

lm_routes   1 row per route    route_id
lm_stops    1 row per stop     route_id, stop_id
lm_packages 1 row per package  route_id, stop_id, package_id
travel_times.json (1.8 GB) is skipped: no question or model feature needs it.
"""
import json
import re
from pathlib import Path

import boto3
import pandas as pd
from botocore import UNSIGNED
from botocore.config import Config

import backend as b

SRC_BUCKET = "amazon-last-mile-challenges"  # public, us-east-1, owner pays for downloads
SRC = "almrrc2021/almrrc2021-data-training/model_build_inputs/"
FILES = ["route_data.json", "package_data.json", "actual_sequences.json"]
DATA = Path(__file__).parent / "data"
SEP = re.compile(r"[\s,:]*")


def download():
    DATA.mkdir(exist_ok=True)
    s3 = boto3.client("s3", region_name="us-east-1", config=Config(signature_version=UNSIGNED))  # no credentials needed
    for f in FILES:
        if not (DATA / f).exists():
            print("  download", f)
            s3.download_file(SRC_BUCKET, SRC + f, str(DATA / f))


def items(name):
    """Yield (key, value) of a top-level JSON object one entry at a time.
    json.load(package_data.json) needs ~4 GB RAM; this holds the text plus one route."""
    s, dec = (DATA / name).read_text(encoding="utf-8"), json.JSONDecoder()  # json reads the file's NaN values
    i = s.index("{") + 1
    while True:
        i = SEP.match(s, i).end()
        if s[i] == "}":
            return
        key, i = dec.raw_decode(s, i)
        val, i = dec.raw_decode(s, SEP.match(s, i).end())
        yield key, val


def flatten():
    seq = {rid: v["actual"] for rid, v in items("actual_sequences.json")}
    routes, stops, packages = [], [], []
    for rid, r in items("route_data.json"):
        routes.append((rid, r["station_code"], r["date_YYYY_MM_DD"], r["departure_time_utc"],
                       r["executor_capacity_cm3"], r["route_score"]))
        stops += [(rid, sid, s["type"], s["zone_id"], s["lat"], s["lng"], seq.get(rid, {}).get(sid))
                  for sid, s in r["stops"].items()]
    for rid, r in items("package_data.json"):
        for sid, pk in r.items():
            packages += [(rid, sid, pid, p["scan_status"], p["time_window"]["start_time_utc"],
                          p["time_window"]["end_time_utc"], p["planned_service_time_seconds"],
                          p["dimensions"]["depth_cm"], p["dimensions"]["height_cm"], p["dimensions"]["width_cm"])
                         for pid, p in pk.items()]

    routes = pd.DataFrame(routes, columns=["route_id", "station_code", "route_date", "departure_time",
                                           "executor_capacity_cm3", "route_score"])
    stops = pd.DataFrame(stops, columns=["route_id", "stop_id", "type", "zone_id", "lat", "lng", "visit_order"])
    packages = pd.DataFrame(packages, columns=["route_id", "stop_id", "package_id", "scan_status", "tw_start",
                                               "tw_end", "planned_service_time_seconds", "depth_cm", "height_cm", "width_cm"])

    # types and derived columns
    routes["departure_ts"] = pd.to_datetime(routes.route_date + " " + routes.departure_time)
    routes["route_date"] = pd.to_datetime(routes.route_date)
    routes = routes.drop(columns="departure_time")
    packages["tw_start"], packages["tw_end"] = pd.to_datetime(packages.tw_start), pd.to_datetime(packages.tw_end)
    packages["has_time_window"] = packages.tw_end.notna()
    packages["volume_cm3"] = (packages.depth_cm * packages.height_cm * packages.width_cm).round(1)
    stops["visit_order"] = stops.visit_order.astype("Int64")
    stops = stops.merge(packages.groupby(["route_id", "stop_id"]).size().rename("n_packages").reset_index(),
                        on=["route_id", "stop_id"], how="left").fillna({"n_packages": 0}).astype({"n_packages": int})
    routes = routes.merge(stops.groupby("route_id").size().rename("n_stops").reset_index(), on="route_id") \
                   .merge(packages.groupby("route_id").agg(n_packages=("package_id", "size"),
                                                          total_volume_cm3=("volume_cm3", "sum")).reset_index(),
                          on="route_id", how="left")

    # data checks. Errors must be 0; observations are real data facts, kept and reported
    keys = ["route_id", "stop_id"]
    checks = {
        "routes": len(routes), "stops": len(stops), "packages": len(packages),
        "error_packages_without_stop": int((~pd.MultiIndex.from_frame(packages[keys])
                                            .isin(pd.MultiIndex.from_frame(stops[keys]))).sum()),
        "error_stops_without_visit_order": int(stops.visit_order.isna().sum()),
        "error_duplicate_rows": int(packages.duplicated(keys + ["package_id"]).sum()),
        "obs_dropoffs_without_zone": int(((stops.type == "Dropoff") & stops.zone_id.isna()).sum()),
        "obs_packages_at_2plus_stops": int(packages.groupby(["route_id", "package_id"]).stop_id.nunique().gt(1).sum()),  # attempted, then delivered elsewhere
    }
    if any(v for k, v in checks.items() if k.startswith("error_")):
        raise ValueError(f"data checks failed: {checks}")
    return {"lm_routes": routes, "lm_stops": stops, "lm_packages": packages}, checks


def run():
    download()
    tables, checks = flatten()
    s3 = b.session.client("s3")
    if b.BUCKET not in [x["Name"] for x in s3.list_buckets()["Buckets"]]:
        s3.create_bucket(Bucket=b.BUCKET, CreateBucketConfiguration={"LocationConstraint": b.REGION})
    import awswrangler as wr
    wr.catalog.create_database(b.DATABASE, exist_ok=True, boto3_session=b.session)
    for name, df in tables.items():
        b.save(df, name, mode="overwrite")
        print(f"  {name}: {len(df):,} rows -> s3://{b.BUCKET}/{name}/")
    return checks


if __name__ == "__main__":
    print(run())
